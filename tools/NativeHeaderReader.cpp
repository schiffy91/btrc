#include <llvm/ADT/ScopeExit.h>
#include <llvm/ADT/StringExtras.h>
#include <chrono>
#include <clang/Tooling/CompilationDatabase.h>
#include <fstream>
#include <iostream>
#include <clang/APINotes/APINotesOptions.h>
#include <clang/Basic/CodeGenOptions.h>
#include <llvm/Support/Path.h>
#if defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
#include <array>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#endif
#include <clang/Basic/FileManager.h>
#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/PreprocessorOptions.h>
#include <clang/Lex/HeaderSearchOptions.h>
#include <clang/Frontend/CompilerInvocation.h>
#include <llvm/Support/SHA256.h>
#include <cstdlib>
#if !defined(_WIN32)
#include <sys/stat.h>
#include <sys/file.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#endif
#if defined(__APPLE__)
#include <crt_externs.h>
#endif
#include <clang/AST/ASTConsumer.h>
#include <clang/AST/ASTContext.h>
#include <clang/AST/Attr.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/AST/RecordLayout.h>
#include <clang/Basic/TargetInfo.h>
#include <clang/Basic/Version.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Frontend/TextDiagnosticPrinter.h>
#include <clang/Index/USRGeneration.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/ArgumentsAdjusters.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/Support/VirtualFileSystem.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/Support/CommandLine.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/FileUtilities.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/Program.h>
#include <llvm/Support/Regex.h>
#include <llvm/Support/StringSaver.h>
#include <llvm/Support/raw_ostream.h>

#include <map>
#include <memory>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

// One read-only index for a translation unit. The union filters indexing work;
// it grants no semantic authority to an individual native request.
class NativeHeaderIndex : public clang::RecursiveASTVisitor<NativeHeaderIndex> {
	clang::ASTContext& context;
	const std::set<std::string>& selectedNames;

public:
	std::map<std::string, const clang::NamedDecl*> declarations;
	std::map<std::string, const clang::ObjCInterfaceDecl*> interfaces;
	std::map<std::string, const clang::ObjCProtocolDecl*> protocols;
	std::map<std::string, const clang::CXXRecordDecl*> cppClasses;
	std::map<std::string, clang::Selector> selectors;
	std::vector<std::string> ambiguous;

	NativeHeaderIndex(clang::ASTContext& value, const std::set<std::string>& names) : context(value), selectedNames(names) {
		TraverseDecl(value.getTranslationUnitDecl());
	}

	static std::string declarationName(const clang::NamedDecl* declaration) {
		if (const auto* method = llvm::dyn_cast<clang::ObjCMethodDecl>(declaration)) {
			if (const auto* owner = method->getClassInterface()) {
				return std::string(method->isClassMethod() ? "+[" : "-[") + owner->getNameAsString() + " " + method->getSelector().getAsString() + "]";
			}
			if (const auto* owner = llvm::dyn_cast<clang::ObjCProtocolDecl>(method->getDeclContext())) {
				return std::string(method->isClassMethod() ? "+[" : "-[") + owner->getNameAsString() + " " + method->getSelector().getAsString() + "]";
			}
		}
		return declaration->getQualifiedNameAsString();
	}

	bool VisitObjCInterfaceDecl(clang::ObjCInterfaceDecl* value) {
		interfaces[value->getNameAsString()] = value->getCanonicalDecl();
		return true;
	}

	bool VisitObjCProtocolDecl(clang::ObjCProtocolDecl* value) {
		protocols[value->getNameAsString()] = value->getCanonicalDecl();
		return true;
	}

	bool VisitObjCPropertyDecl(clang::ObjCPropertyDecl* property) {
		// Implicit accessors are public SDK methods even though the general
		// AST traversal intentionally skips implicit implementation details.
		if (auto* getter = property->getGetterMethodDecl()) { VisitNamedDecl(getter); }
		if (auto* setter = property->getSetterMethodDecl()) { VisitNamedDecl(setter); }
		return true;
	}

	bool VisitNamedDecl(clang::NamedDecl* value) {
		if (const auto* record = llvm::dyn_cast<clang::CXXRecordDecl>(value)) {
			if (record->isInjectedClassName()) { return true; }
			cppClasses[record->getQualifiedNameAsString()] = record->getCanonicalDecl();
		}
		if (const auto* method = llvm::dyn_cast<clang::ObjCMethodDecl>(value)) {
			selectors[method->getSelector().getAsString()] = method->getSelector();
			// Class and protocol names occupy separate Objective-C namespaces.
			// Resolve protocol selections after traversal, through Clang lookup.
			if (llvm::isa<clang::ObjCProtocolDecl>(method->getDeclContext())) { return true; }
		}
		auto name = declarationName(value);
		if (!selectedNames.count(name)) { return true; }
		auto found = declarations.find(name);
		if (found != declarations.end() && found->second->getCanonicalDecl() != value->getCanonicalDecl()) {
			// C tags occupy a different namespace: `typedef struct Foo Foo` is
			// one usable ordinary name, not an ambiguous declaration request.
			if (!context.getLangOpts().CPlusPlus && llvm::isa<clang::TagDecl>(value) != llvm::isa<clang::TagDecl>(found->second)) {
				if (llvm::isa<clang::TagDecl>(found->second)) { declarations[name] = value; }
				return true;
			}
			ambiguous.push_back(name);
		} else {
			declarations[name] = value;
		}
		return true;
	}
};

// Build-time semantic reader for C ABI declarations and Objective-C methods.
// Unsupported declarations fail rather than losing type/lifetime information.
// Both BTRC frontends consume the same checked semantic model.
class NativeHeaderReader {
	const NativeHeaderIndex* header = nullptr;
	clang::ASTContext* context = nullptr;
	std::set<std::string> requested;
	std::vector<std::string> recordPaths;
	std::set<std::string> recordValues;
	std::map<std::string, llvm::json::Object> selectedInterfaces;
	std::vector<std::string> errors;
	llvm::json::Array exports;
	std::map<std::string, const clang::RecordDecl*> pendingRecords;
	std::map<std::string, llvm::json::Object> records;
	std::string target;
	bool bigEndian = false;
	unsigned characterBits = 0;

	std::string declarationIdentity(const clang::NamedDecl* declaration) {
		llvm::SmallString<128> identity;
		if (clang::index::generateUSRForDecl(declaration->getCanonicalDecl(), identity)) {
			errors.push_back("Cannot identify native declaration: " + declaration->getQualifiedNameAsString());
		}
		return identity.str().str();
	}

	std::string objectiveCReceiver(const std::string& name) const {
		if (name.size() < 5 || (name[0] != '+' && name[0] != '-') || name[1] != '[' || name.back() != ']') { return ""; }
		auto separator = name.find(' ', 2);
		return separator == std::string::npos ? "" : name.substr(2, separator - 2);
	}

	const clang::ObjCMethodDecl* lookupObjectiveCMethod(const std::string& name) const {
		auto receiver = objectiveCReceiver(name);
		if (receiver.empty()) { return nullptr; }
		auto selector = header->selectors.find(name.substr(receiver.size() + 3, name.size() - receiver.size() - 4));
		if (selector == header->selectors.end()) { return nullptr; }
		auto interface = header->interfaces.find(receiver);
		if (interface == header->interfaces.end()) {
			auto protocol = header->protocols.find(receiver);
			if (protocol == header->protocols.end()) { return nullptr; }
			const auto* definition = protocol->second->getDefinition();
			return definition ? definition->lookupMethod(selector->second, name[0] == '-') : nullptr;
		}
		const auto* definition = interface->second->getDefinition();
		if (!definition) { return nullptr; }
		// Clang owns superclass/category/protocol lookup and the declaration's ABI.
		return definition->lookupMethod(selector->second, name[0] == '-');
	}

	std::string requestRecord(const clang::RecordDecl* record, bool opaque) {
		auto identity = declarationIdentity(record);
		if (!opaque) {
			if (llvm::isa<clang::CXXRecordDecl>(record)) {
				if (!requested.count(record->getQualifiedNameAsString())) { errors.push_back("C++ record adapters require a selected SDK class: " + record->getQualifiedNameAsString()); }
				return identity;
			}
			else if (const auto* definition = record->getDefinition()) { pendingRecords.emplace(identity, definition); }
			else { errors.push_back("Incomplete by-value native record: " + record->getQualifiedNameAsString()); }
		}
		return identity;
	}

	const clang::CXXMethodDecl* lookupCppMethod(const clang::CXXRecordDecl* record, const std::string& name, bool zeroParameters) {
		const auto* definition = record->getDefinition();
		if (!definition) { return nullptr; }
		auto matches = definition->lookup(&context->Idents.get(name));
		if (!matches.empty()) {
			const clang::CXXMethodDecl* selected = nullptr;
			for (const auto* candidate : matches) {
				const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(candidate);
				if (!method) { errors.push_back("C++ selection is not a public non-template method: " + name); return nullptr; }
				if (zeroParameters && method->getNumParams() != 0) { continue; }
				if (selected) { errors.push_back("Ambiguous C++ method: " + record->getQualifiedNameAsString() + "::" + name); return nullptr; }
				selected = method;
			}
			return selected;
		}
		const clang::CXXMethodDecl* selected = nullptr;
		for (const auto& base : definition->bases()) {
			if (base.getAccessSpecifier() != clang::AS_public || base.isVirtual()) { continue; }
			const auto* baseRecord = base.getType()->getAsCXXRecordDecl();
			if (!baseRecord) { continue; }
			if (const auto* method = lookupCppMethod(baseRecord, name, zeroParameters)) {
				if (selected) { errors.push_back("Ambiguous inherited C++ method: " + name); return nullptr; }
				selected = method;
			}
		}
		return selected;
	}

	const clang::CXXMethodDecl* lookupCppMethod(const std::string& name) {
		auto separator = name.rfind("::");
		if (separator == std::string::npos) { return nullptr; }
		auto receiver = header->cppClasses.find(name.substr(0, separator));
		std::string method = name.substr(separator + 2);
		bool zeroParameters = method.size() > 2 && method.compare(method.size() - 2, 2, "()") == 0;
		if (zeroParameters) { method.resize(method.size() - 2); }
		return receiver == header->cppClasses.end() ? nullptr : lookupCppMethod(receiver->second, method, zeroParameters);
	}

	void requestCppRecordValue(const std::string& name) {
		auto found = header->cppClasses.find(name);
		const auto* record = found == header->cppClasses.end() ? nullptr : found->second->getDefinition();
		if (!requested.count(name) || !record || record->isUnion() || !record->isStandardLayout() || !record->isTriviallyCopyable() || !record->hasTrivialDestructor() || record->getNumBases() != 0 || record->field_empty()) {
			errors.push_back("C++ record values require selected complete public scalar-only trivial records: " + name); return;
		}
		for (const auto* field : record->fields()) {
			auto value = field->getType();
			if (field->getAccess() != clang::AS_public || field->isAnonymousStructOrUnion() || field->isBitField() || field->getName().empty() || value.isVolatileQualified() || value.isRestrictQualified() || !(value->isIntegerType() || value->isEnumeralType() || value->isRealFloatingType())) {
				errors.push_back("C++ record values require accessible scalar fields: " + name + "::" + field->getNameAsString()); return;
			}
		}
		pendingRecords.emplace(declarationIdentity(record), record);
	}

	std::string requestInterface(const clang::ObjCInterfaceDecl* interface) {
		auto identity = declarationIdentity(interface);
		if (selectedInterfaces.count(identity)) { return identity; }
		const auto* definition = interface->getDefinition();
		llvm::json::Object description{{"name", interface->getNameAsString()}, {"identity", identity}, {"complete", definition != nullptr}, {"superclass", ""}};
		selectedInterfaces.emplace(identity, std::move(description));
		if (definition && definition->getSuperClass()) {
			selectedInterfaces.at(identity)["superclass"] = requestInterface(definition->getSuperClass());
		}
		return identity;
	}

	llvm::json::Object qualifiers(clang::QualType value) const {
		llvm::json::Object result{{"const", value.isConstQualified()}, {"volatile", value.isVolatileQualified()}, {"restrict", value.isRestrictQualified()}};
		auto nullable = value->getNullability();
		if (!nullable) { result["nullability"] = "unannotated"; }
		else if (*nullable == clang::NullabilityKind::NonNull) { result["nullability"] = "nonnull"; }
		else if (*nullable == clang::NullabilityKind::Nullable) { result["nullability"] = "nullable"; }
		else if (*nullable == clang::NullabilityKind::NullableResult) { result["nullability"] = "nullable_result"; }
		else { result["nullability"] = "unspecified"; }
		return result;
	}

	llvm::json::Object type(clang::QualType value, bool indirect = false) {
		auto result = qualifiers(value);
		if (value.hasAddressSpace()) { errors.push_back("Native address spaces are not implemented: " + value.getAsString()); }
		const clang::Type* node = value.getTypePtr();
		if (const auto* object = llvm::dyn_cast<clang::ObjCObjectPointerType>(node)) {
			result["kind"] = "objc_object";
			const auto* interface = object->getInterfaceDecl();
			result["name"] = interface ? interface->getNameAsString() : "";
			result["identity"] = interface ? requestInterface(interface) : "";
			result["class_object"] = object->isObjCClassType() || object->isObjCQualifiedClassType();
			llvm::json::Array protocols;
			for (const auto* protocol : object->quals()) { protocols.push_back(protocol->getNameAsString()); }
			result["protocols"] = std::move(protocols);
			llvm::json::Array arguments;
			for (auto argument : object->getObjectType()->getTypeArgs()) { arguments.push_back(type(argument)); }
			result["type_arguments"] = std::move(arguments);
		} else if (const auto* block = llvm::dyn_cast<clang::BlockPointerType>(node)) {
			result["kind"] = "objc_block";
			result["signature"] = type(block->getPointeeType());
		} else if (const auto* alias = llvm::dyn_cast<clang::TypedefType>(node)) {
			result["kind"] = "typedef";
			result["name"] = alias->getDecl()->getQualifiedNameAsString();
			result["underlying"] = type(alias->getDecl()->getUnderlyingType(), indirect);
		} else if (const auto* pointer = llvm::dyn_cast<clang::PointerType>(node)) {
			result["kind"] = "pointer";
			result["pointee"] = type(pointer->getPointeeType(), true);
		} else if (const auto* builtin = llvm::dyn_cast<clang::BuiltinType>(node)) {
			result["kind"] = "builtin";
			result["name"] = builtin->getName(context->getPrintingPolicy()).str();
			if (!value->isVoidType()) {
				result["bits"] = static_cast<int64_t>(context->getTypeSize(value));
				result["alignment_bits"] = static_cast<int64_t>(context->getTypeAlign(value));
				if (value->isIntegerType()) { result["signed"] = value->isSignedIntegerType(); }
			}
		} else if (const auto* record = llvm::dyn_cast<clang::RecordType>(node)) {
			result["kind"] = "record";
			result["name"] = record->getDecl()->getQualifiedNameAsString();
			result["identity"] = requestRecord(record->getDecl(), indirect);
			result["record_kind"] = record->getDecl()->isUnion() ? "union" : "struct";
			result["tag_name"] = record->getDecl()->getNameAsString();
			result["complete"] = record->getDecl()->getDefinition() != nullptr;
			result["opaque"] = recordValues.count(record->getDecl()->getQualifiedNameAsString()) ? false : indirect || llvm::isa<clang::CXXRecordDecl>(record->getDecl());
		} else if (const auto* array = llvm::dyn_cast<clang::ConstantArrayType>(node)) {
			result["kind"] = "array";
			result["element"] = type(array->getElementType());
			llvm::SmallString<32> count;
			array->getSize().toStringUnsigned(count);
			result["count"] = count.str().str();
		} else if (const auto* array = llvm::dyn_cast<clang::IncompleteArrayType>(node)) {
			result["kind"] = "array";
			result["element"] = type(array->getElementType());
			result["count"] = nullptr;
		} else if (const auto* enumeration = llvm::dyn_cast<clang::EnumType>(node)) {
			result["kind"] = "enum";
			result["name"] = enumeration->getDecl()->getIdentifier() ? enumeration->getDecl()->getQualifiedNameAsString() : "";
			result["identity"] = declarationIdentity(enumeration->getDecl());
			result["underlying"] = type(enumeration->getDecl()->getIntegerType());
		} else if (const auto* function = llvm::dyn_cast<clang::FunctionProtoType>(node)) {
			result["kind"] = "function";
			result["return_type"] = type(function->getReturnType());
			result["variadic"] = function->isVariadic();
			if (function->getCallConv() != clang::CC_C) { errors.push_back("Unsupported calling convention: " + value.getAsString()); }
			result["calling_convention"] = "c";
			llvm::json::Array parameters;
			for (auto parameter : function->param_types()) { parameters.push_back(type(parameter)); }
			result["parameters"] = std::move(parameters);
		} else {
			auto desugared = value.getSingleStepDesugaredType(*context);
			if (desugared != value) {
				result["kind"] = "qualified";
				result["underlying"] = type(desugared, indirect);
			} else {
				errors.push_back("Unsupported native type: " + value.getAsString());
				result["kind"] = "unsupported";
			}
		}
		return result;
	}

	void readRecords() {
		while (!pendingRecords.empty()) {
			auto next = pendingRecords.extract(pendingRecords.begin());
			if (records.count(next.key())) { continue; }
			const auto* record = next.mapped();
			const auto& layout = context->getASTRecordLayout(record);
			llvm::json::Array fields;
			unsigned index = 0;
			for (const auto* field : record->fields()) {
				llvm::json::Object entry{{"name", field->getNameAsString()}, {"type", type(field->getType())}, {"offset_bits", std::to_string(layout.getFieldOffset(index++))}, {"anonymous", field->isAnonymousStructOrUnion()}};
				if (field->isBitField()) { entry["width_bits"] = std::to_string(field->getBitWidthValue()); }
				fields.push_back(std::move(entry));
			}
			llvm::json::Object description{{"identity", next.key()}, {"name", record->getQualifiedNameAsString()}, {"kind", record->isUnion() ? "union" : "struct"}, {"size_bits", std::to_string(layout.getSize().getQuantity() * characterBits)}, {"alignment_bits", std::to_string(layout.getAlignment().getQuantity() * characterBits)}, {"fields", std::move(fields)}};
			records.emplace(next.key(), std::move(description));
		}
	}

	std::string returnedOwnership(const clang::Decl* function) const {
		if (function->hasAttr<clang::CFReturnsRetainedAttr>()) { return "cf_retained"; }
		if (function->hasAttr<clang::CFReturnsNotRetainedAttr>()) { return "cf_not_retained"; }
		if (function->hasAttr<clang::NSReturnsRetainedAttr>()) { return "ns_retained"; }
		if (function->hasAttr<clang::NSReturnsNotRetainedAttr>()) { return "ns_not_retained"; }
		if (function->hasAttr<clang::NSReturnsAutoreleasedAttr>()) { return "ns_autoreleased"; }
		return "unspecified";
	}

	llvm::json::Array parameters(llvm::ArrayRef<clang::ParmVarDecl*> values) {
		llvm::json::Array result;
		for (const auto* parameter : values) {
			if (parameter->hasAttr<clang::PassObjectSizeAttr>()) { errors.push_back("Implicit native object-size parameters are not implemented: " + parameter->getNameAsString()); }
			result.push_back(llvm::json::Object{{"name", parameter->getNameAsString()}, {"cf_consumed", parameter->hasAttr<clang::CFConsumedAttr>()}, {"ns_consumed", parameter->hasAttr<clang::NSConsumedAttr>()}, {"no_escape", parameter->hasAttr<clang::NoEscapeAttr>()}});
		}
		return result;
	}

	std::string methodFamily(const clang::ObjCMethodDecl* method) {
		switch (method->getMethodFamily()) {
		case clang::OMF_None: return "none";
		case clang::OMF_alloc: return "alloc";
		case clang::OMF_copy: return "copy";
		case clang::OMF_init: return "init";
		case clang::OMF_initialize: return "initialize";
		case clang::OMF_mutableCopy: return "mutable_copy";
		case clang::OMF_new: return "new";
		case clang::OMF_autorelease: return "autorelease";
		case clang::OMF_dealloc: return "dealloc";
		case clang::OMF_finalize: return "finalize";
		case clang::OMF_release: return "release";
		case clang::OMF_retain: return "retain";
		case clang::OMF_retainCount: return "retain_count";
		case clang::OMF_self: return "self";
		case clang::OMF_performSelector: return "perform_selector";
		}
		errors.push_back("Unsupported Objective-C method family: " + NativeHeaderIndex::declarationName(method));
		return "unsupported";
	}

	llvm::json::Object declaration(const clang::NamedDecl* value) {
		auto location = context->getSourceManager().getPresumedLoc(value->getLocation());
		llvm::json::Object result{{"name", NativeHeaderIndex::declarationName(value)}};
		if (location.isValid()) {
			result["source"] = location.getFilename();
			result["line"] = static_cast<int64_t>(location.getLine());
			result["column"] = static_cast<int64_t>(location.getColumn());
		}
		if (const auto* method = llvm::dyn_cast<clang::ObjCMethodDecl>(value)) {
			const auto* owner = method->getClassInterface();
			const auto* protocol = llvm::dyn_cast<clang::ObjCProtocolDecl>(method->getDeclContext());
			if (!owner && !protocol) { errors.push_back("Unsupported Objective-C method owner: " + NativeHeaderIndex::declarationName(value)); return result; }
			result["kind"] = "objc_method";
			result["protocol_owner"] = protocol != nullptr;
			result["optional"] = method->isOptional();
			result["identity"] = declarationIdentity(method);
			result["owner"] = owner ? owner->getNameAsString() : protocol->getNameAsString();
			result["selector"] = method->getSelector().getAsString();
			result["class_method"] = method->isClassMethod();
			llvm::SmallVector<clang::QualType, 8> argumentTypes;
			for (const auto* parameter : method->parameters()) { argumentTypes.push_back(parameter->getType()); }
			clang::FunctionProtoType::ExtProtoInfo signature;
			signature.Variadic = method->isVariadic();
			result["type"] = type(context->getFunctionType(method->getReturnType(), argumentTypes, signature));
			result["parameter_semantics"] = parameters(method->parameters());
			result["returned_ownership"] = returnedOwnership(method);
			result["method_family"] = methodFamily(method);
			result["consumes_self"] = method->hasAttr<clang::NSConsumesSelfAttr>();
			result["related_result"] = method->hasRelatedResultType();
			result["returns_inner_pointer"] = method->hasAttr<clang::ObjCReturnsInnerPointerAttr>();
		} else if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(value)) {
			if (method->getAccess() != clang::AS_public || method->isDeleted() || method->isStatic() || method->isVariadic() || method->isVolatile() || method->getRefQualifier() != clang::RQ_None || method->isOverloadedOperator() || llvm::isa<clang::CXXConstructorDecl>(method) || llvm::isa<clang::CXXDestructorDecl>(method) || llvm::isa<clang::CXXConversionDecl>(method) || method->getTemplatedKind() != clang::FunctionDecl::TK_NonTemplate) {
				errors.push_back("C++ methods require unambiguous public non-template instance methods: " + NativeHeaderIndex::declarationName(method));
			}
			result["kind"] = "cxx_method";
			result["identity"] = declarationIdentity(method);
			result["owner"] = method->getParent()->getQualifiedNameAsString();
			result["receiver"] = method->getParent()->getQualifiedNameAsString();
			result["method_name"] = method->getNameAsString();
			result["const_method"] = method->isConst();
			result["type"] = type(method->getType());
			result["parameter_semantics"] = parameters(method->parameters());
		} else if (const auto* function = llvm::dyn_cast<clang::FunctionDecl>(value)) {
			if (function->hasAttr<clang::OverloadableAttr>()) { errors.push_back("Overloadable C adapters are not implemented: " + value->getQualifiedNameAsString()); }
			if (llvm::isa<clang::CXXMethodDecl>(function) || (context->getLangOpts().CPlusPlus && !function->isExternC())) {
				errors.push_back("C++ function adapters are not implemented: " + value->getQualifiedNameAsString());
			}
			result["kind"] = "function";
			const auto* symbol = function->getAttr<clang::AsmLabelAttr>();
			result["link_name"] = symbol ? symbol->getLabel().str() : function->getNameAsString();
			result["type"] = type(function->getType());
			result["returned_ownership"] = returnedOwnership(function);
			result["parameter_semantics"] = parameters(function->parameters());
		} else if (const auto* variable = llvm::dyn_cast<clang::VarDecl>(value)) {
			if (!variable->isFileVarDecl() || variable->getTLSKind() != clang::VarDecl::TLS_None) {
				errors.push_back("Native thread-local/local storage is not implemented: " + value->getQualifiedNameAsString());
			}
			// A C++ const integral variable with a constant initializer is an SDK
			// constant like an enumerator: its evaluated value is the contract, not
			// the C++-linkage storage BTRC cannot address from strict C.
			clang::Expr::EvalResult evaluated;
			if (context->getLangOpts().CPlusPlus && !variable->isExternC() && !variable->hasAttr<clang::AsmLabelAttr>() && variable->getType().isConstQualified() && variable->getType()->isIntegralOrEnumerationType() && variable->getInit() != nullptr && variable->getInit()->EvaluateAsInt(evaluated, *context)) {
				result["kind"] = "enum_constant";
				result["type"] = type(variable->getType().getUnqualifiedType());
				result["enum_identity"] = "";
				llvm::SmallString<32> decimal;
				evaluated.Val.getInt().toString(decimal);
				result["value"] = decimal.str().str();
				return result;
			}
			if (variable->hasAttr<clang::AsmLabelAttr>() || (context->getLangOpts().CPlusPlus && !variable->isExternC())) {
				errors.push_back("Renamed/C++ native globals require adapter lowering: " + value->getQualifiedNameAsString());
			}
			// A read-only pointer slot is not a pointer to read-only data. Keep
			// slot immutability separate while preserving every pointee qualifier.
			auto variableType = variable->getType();
			auto valueQualifiers = variableType.getQualifiers();
			valueQualifiers.removeConst();
			result["kind"] = "global";
			result["read_only"] = variableType.isConstQualified();
			// Object reads are owned values, not exposed storage. Preserve SDK
			// nullability sugar; the importer handles the read-only pointer slot.
			result["type"] = type(variableType->isObjCObjectPointerType() ? variableType : context->getQualifiedType(variableType.getUnqualifiedType(), valueQualifiers));
		} else if (const auto* alias = llvm::dyn_cast<clang::TypedefNameDecl>(value)) {
			result["kind"] = "typedef";
			result["type"] = type(alias->getUnderlyingType(), alias->getUnderlyingType()->isIncompleteType());
		} else if (const auto* constant = llvm::dyn_cast<clang::EnumConstantDecl>(value)) {
			result["kind"] = "enum_constant";
			result["type"] = type(constant->getType());
			result["enum_identity"] = declarationIdentity(llvm::cast<clang::EnumDecl>(constant->getDeclContext()));
			llvm::SmallString<32> decimal;
			constant->getInitVal().toString(decimal);
			result["value"] = decimal.str().str();
		} else if (const auto* record = llvm::dyn_cast<clang::CXXRecordDecl>(value)) {
			const auto* definition = record->getDefinition();
			if (!definition || definition->getDescribedClassTemplate() || llvm::isa<clang::ClassTemplateSpecializationDecl>(record)) {
				errors.push_back("C++ resources require complete non-template SDK classes: " + NativeHeaderIndex::declarationName(record));
			}
			bool constructor = false;
			if (definition && !definition->isAbstract()) {
				for (const auto* candidate : definition->ctors()) {
					if (candidate->getNumParams() == 0 && candidate->getAccess() == clang::AS_public && !candidate->isDeleted() && candidate->getTemplatedKind() == clang::FunctionDecl::TK_NonTemplate) { constructor = true; }
				}
			}
			const auto* destructor = definition ? definition->getDestructor() : nullptr;
			result["kind"] = "cxx_class";
			result["type"] = type(context->getRecordType(record), true);
			result["default_constructor"] = constructor;
			result["public_destructor"] = definition && (destructor ? destructor->getAccess() == clang::AS_public && !destructor->isDeleted() : definition->hasTrivialDestructor());
			result["trivially_copyable"] = definition && definition->isTriviallyCopyable();
			result["trivially_destructible"] = definition && definition->hasTrivialDestructor();
		} else if (const auto* record = llvm::dyn_cast<clang::RecordDecl>(value)) {
			result["kind"] = "record";
			result["type"] = type(context->getRecordType(record), record->getDefinition() == nullptr);
		} else {
			errors.push_back("Unsupported native declaration: " + value->getQualifiedNameAsString());
		}
		return result;
	}

public:
	explicit NativeHeaderReader(const std::vector<std::string>& symbols, const std::vector<std::string>& paths, const std::vector<std::string>& values) : requested(symbols.begin(), symbols.end()), recordPaths(paths), recordValues(values.begin(), values.end()) {}

	void requestRecordPath(const std::string& path) {
		auto separator = path.find('.');
		if (separator == std::string::npos) { errors.push_back("Record path requires an owner and field: " + path); return; }
		auto name = path.substr(0, separator);
		if (!requested.count(name)) { errors.push_back("Record path requires a selected SDK record owner: " + path); return; }
		auto owner = header->declarations.find(name);
		const auto* declaration = owner == header->declarations.end() ? nullptr : owner->second;
		clang::QualType current;
		if (const auto* type = llvm::dyn_cast_or_null<clang::TypedefNameDecl>(declaration)) {
			current = type->getUnderlyingType();
		} else if (const auto* record = llvm::dyn_cast_or_null<clang::RecordDecl>(declaration)) {
			current = context->getRecordType(record);
		} else { errors.push_back("Record path requires a selected SDK record owner: " + path); return; }
		if (!current->isPointerType() && !current->isRecordType()) { errors.push_back("Record path requires a record or pointer owner: " + path); return; }
		std::set<const clang::TagDecl*> visited;
		while (separator != std::string::npos) {
			auto begin = separator + 1;
			separator = path.find('.', begin);
			auto name = path.substr(begin, separator == std::string::npos ? separator : separator - begin);
			if (current.isVolatileQualified() || current.isRestrictQualified()) { errors.push_back("Record path cannot traverse qualified mutation: " + path); return; }
			if (const auto* pointer = current->getAs<clang::PointerType>()) { current = pointer->getPointeeType(); }
			if (current.isVolatileQualified() || current.isRestrictQualified()) { errors.push_back("Record path cannot traverse qualified mutation: " + path); return; }
			const auto* recordType = current->getAs<clang::RecordType>();
			const auto* record = recordType ? recordType->getDecl()->getDefinition() : nullptr;
			if (!record || (!record->isStruct() && !record->isUnion()) || !visited.insert(record->getCanonicalDecl()).second) { errors.push_back("Record path requires noncyclic complete SDK records: " + path); return; }
			const clang::FieldDecl* selected = nullptr;
			for (const auto* field : record->fields()) { if (field->getNameAsString() == name) { selected = field; break; } }
			if (!selected || selected->isAnonymousStructOrUnion() || selected->isBitField()) { errors.push_back("Record path names an unavailable SDK field: " + path); return; }
			requestRecord(record, false);
			current = selected->getType();
		}
	}

	void read(clang::ASTContext& value, const NativeHeaderIndex& index) {
		if (value.getDiagnostics().hasErrorOccurred()) { return; }
		context = &value;
		header = &index;
		target = value.getTargetInfo().getTriple().str();
		bigEndian = value.getTargetInfo().isBigEndian();
		characterBits = value.getTargetInfo().getCharWidth();
		for (const auto& name : index.ambiguous) {
			if (requested.count(name)) { errors.push_back("Ambiguous native declaration: " + name); }
		}
		for (const auto& name : recordValues) { requestCppRecordValue(name); }
		for (const auto& name : requested) {
			auto found = header->declarations.find(name);
			const clang::NamedDecl* selected = found == header->declarations.end() ? lookupObjectiveCMethod(name) : found->second;
			if (!selected && value.getLangOpts().CPlusPlus) { selected = lookupCppMethod(name); }
			if (!selected) { errors.push_back("Native declaration not found: " + name); }
			else {
				auto exported = declaration(selected);
				if (llvm::isa<clang::CXXMethodDecl>(selected)) {
					exported["name"] = name;
					exported["receiver"] = name.substr(0, name.rfind("::"));
				}
				if (llvm::isa<clang::ObjCMethodDecl>(selected)) {
					exported["name"] = name;
					exported["receiver"] = objectiveCReceiver(name);
					auto receiver = header->interfaces.find(objectiveCReceiver(name));
					if (receiver != header->interfaces.end()) { requestInterface(receiver->second); }
					if (const auto* owner = llvm::cast<clang::ObjCMethodDecl>(selected)->getClassInterface()) { requestInterface(owner); }
				}
				exports.push_back(std::move(exported));
			}
		}
		for (const auto& path : recordPaths) { requestRecordPath(path); }
		if (errors.empty() && !value.getDiagnostics().hasErrorOccurred()) { readRecords(); }
		pendingRecords.clear();
		header = nullptr;
		context = nullptr;
	}

	const std::vector<std::string>& diagnostics() const { return errors; }

	llvm::json::Object takeDocument() {
		llvm::json::Array layouts;
		for (auto& record : records) { layouts.push_back(std::move(record.second)); }
		llvm::json::Array interfaceDeclarations;
		for (auto& interface : selectedInterfaces) { interfaceDeclarations.push_back(std::move(interface.second)); }
		return llvm::json::Object{{"schema", "btrc.native-declarations.experimental"}, {"target", target}, {"clang", clang::getClangFullVersion()}, {"big_endian", bigEndian}, {"character_bits", static_cast<int64_t>(characterBits)}, {"declarations", std::move(exports)}, {"records", std::move(layouts)}, {"interfaces", std::move(interfaceDeclarations)}};
	}

	bool publish() {
		if (!errors.empty()) {
			for (const auto& error : errors) { llvm::errs() << "error: " << error << '\n'; }
			return false;
		}
		llvm::outs() << llvm::formatv("{0:2}\n", llvm::json::Value(takeDocument()));
		return true;
	}
};

// One translation unit and compile command, independent semantic selections.
// Sharing the index must not let a selected class authorize a by-value C++
// record in another request, nor leak selected interfaces or layouts.
class NativeHeaderRequests {
	llvm::json::Array inputSelections;
	std::set<std::string> selectedNames;
	std::vector<std::string> identities;
	std::vector<std::unique_ptr<NativeHeaderReader>> readers;

	bool strings(const llvm::json::Object& object, llvm::StringRef key, std::vector<std::string>& values, bool required) {
		const auto* array = object.getArray(key);
		if (!array) { return !required && !object.get(key); }
		for (const auto& item : *array) {
			auto text = item.getAsString();
			if (!text || text->empty() || text->contains('\0')) { return false; }
			values.push_back(text->str());
		}
		return !required || !values.empty();
	}

public:
	const llvm::json::Array& selections() const { return inputSelections; }
	void add(std::string identity, const std::vector<std::string>& symbols, const std::vector<std::string>& paths, const std::vector<std::string>& values) {
		llvm::json::Array names, fields, records;
		for (const auto& name : symbols) { names.push_back(name); }
		for (const auto& name : paths) { fields.push_back(name); }
		for (const auto& name : values) { records.push_back(name); }
		inputSelections.push_back(llvm::json::Array{identity, std::move(names), std::move(fields), std::move(records)});
		selectedNames.insert(symbols.begin(), symbols.end());
		identities.push_back(std::move(identity));
		readers.push_back(std::make_unique<NativeHeaderReader>(symbols, paths, values));
	}

	bool load(llvm::StringRef path) {
		auto input = llvm::MemoryBuffer::getFileOrSTDIN(path);
		if (!input) { llvm::errs() << "error: cannot read native request batch: " << input.getError().message() << '\n'; return false; }
		return loadText((*input)->getBuffer());
	}

	bool loadText(llvm::StringRef text) {
		auto parsed = llvm::json::parse(text);
		if (!parsed) { llvm::errs() << "error: invalid native request batch: " << parsed.takeError() << '\n'; return false; }
		const auto* document = parsed->getAsObject();
		if (!document || document->size() != 2 || document->getString("schema") != "btrc.native-requests.v1") {
			llvm::errs() << "error: expected btrc.native-requests.v1 batch\n"; return false;
		}
		const auto* requests = document->getArray("requests");
		if (!requests || requests->empty()) { llvm::errs() << "error: native request batch must not be empty\n"; return false; }
		std::set<std::string> seen;
		for (const auto& item : *requests) {
			const auto* request = item.getAsObject();
			if (!request) { llvm::errs() << "error: native batch request must be an object\n"; return false; }
			for (const auto& field : *request) {
				if (field.first != "id" && field.first != "symbols" && field.first != "record_paths" && field.first != "record_values") {
					llvm::errs() << "error: unknown native batch request field: " << field.first << '\n'; return false;
				}
			}
			auto identity = request->getString("id");
			std::vector<std::string> symbols, paths, values;
			if (!identity || identity->empty() || identity->contains('\0') || !seen.insert(identity->str()).second ||
				!strings(*request, "symbols", symbols, true) || !strings(*request, "record_paths", paths, false) || !strings(*request, "record_values", values, false)) {
				llvm::errs() << "error: native batch request requires a unique id and string selection arrays\n"; return false;
			}
			add(identity->str(), symbols, paths, values);
		}
		return true;
	}

	void read(clang::ASTContext& context) {
		if (context.getDiagnostics().hasErrorOccurred()) { return; }
		const NativeHeaderIndex index(context, selectedNames);
		for (auto& reader : readers) { reader->read(context, index); }
	}

	bool publish(bool batch) {
		if (!batch) { return readers.front()->publish(); }
		llvm::json::Array results;
		for (size_t index = 0; index < readers.size(); ++index) {
			auto& reader = readers[index];
			llvm::json::Array errors;
			for (const auto& error : reader->diagnostics()) { errors.push_back(error); }
			llvm::json::Object result{{"id", identities[index]}, {"errors", std::move(errors)}};
			result["document"] = reader->diagnostics().empty() ? llvm::json::Value(reader->takeDocument()) : llvm::json::Value(nullptr);
			results.push_back(std::move(result));
		}
		llvm::outs() << llvm::formatv("{0:2}\n", llvm::json::Value(llvm::json::Object{{"schema", "btrc.native-responses.v1"}, {"results", std::move(results)}}));
		return true;
	}
};

// Loaded runtime identity. Admission outside these immutable providers is
// deliberately unavailable until a content-based loaded-image contract exists.
class NativeRuntimeInputs {
public:
	static bool immutableStorePath(llvm::StringRef path) {
		if (!path.starts_with("/nix/store/")) { return false; }
		auto tail = path.drop_front(11);
		auto name = tail.take_until([](char value) { return value == '/'; });
		if (name.size() < 34 || name[32] != '-') { return false; }
		for (auto value : name.take_front(32)) {
			if (llvm::StringRef("0123456789abcdfghijklmnpqrsvwxyz").find(value) == llvm::StringRef::npos) { return false; }
		}
		llvm::sys::fs::file_status status;
		if (llvm::sys::fs::status(path, status) || !llvm::sys::fs::is_regular_file(status) || status.getUser() != 0 || (status.permissions() & llvm::sys::fs::all_write) != llvm::sys::fs::no_perms) { return false; }
		llvm::SmallString<256> parent(path); llvm::sys::path::remove_filename(parent);
		while (parent != "/nix/store") {
			if (parent.empty() || llvm::sys::fs::status(parent, status) || !llvm::sys::fs::is_directory(status) || status.getUser() != 0 || (status.permissions() & llvm::sys::fs::all_write) != llvm::sys::fs::no_perms) { return false; }
			llvm::sys::path::remove_filename(parent);
		}
		if (llvm::sys::fs::status(parent, status) || status.getUser() != 0) { return false; }
		auto untrustedWrites = status.permissions() & (llvm::sys::fs::group_write | llvm::sys::fs::others_write);
		return untrustedWrites == llvm::sys::fs::no_perms || (status.permissions() & llvm::sys::fs::sticky_bit) != llvm::sys::fs::no_perms;
	}
#if defined(__APPLE__)
	static std::string imageUuid(const mach_header* header) {
		if (!header || header->magic != MH_MAGIC_64) { return ""; }
		auto* wide = reinterpret_cast<const mach_header_64*>(header);
		auto* cursor = reinterpret_cast<const unsigned char*>(wide + 1);
		auto* limit = cursor + wide->sizeofcmds;
		for (uint32_t i = 0; i < wide->ncmds; ++i) {
			if (static_cast<size_t>(limit - cursor) < sizeof(load_command)) { return ""; }
			const auto* command = reinterpret_cast<const load_command*>(cursor);
			if (command->cmdsize < sizeof(load_command) || command->cmdsize > static_cast<size_t>(limit - cursor)) { return ""; }
			if (command->cmd == LC_UUID) {
				if (command->cmdsize < sizeof(uuid_command)) { return ""; }
				const auto* uuid = reinterpret_cast<const uuid_command*>(command);
				static const char alphabet[] = "0123456789abcdef"; std::string result;
				for (auto byte : uuid->uuid) { result.push_back(alphabet[byte >> 4]); result.push_back(alphabet[byte & 15]); }
				return result;
			}
			cursor += command->cmdsize;
		}
		return "";
	}
#endif
public:
	static llvm::json::Object capture() {
		std::vector<std::vector<std::string>> images; std::set<std::string> exclusions;
#if defined(__APPLE__)
		auto count = _dyld_image_count();
		for (uint32_t i = 0; i < count; ++i) {
			const char* name = _dyld_get_image_name(i); const auto* header = _dyld_get_image_header(i);
			if (!name || !header) { exclusions.insert("unavailable-image"); continue; }
			std::string path(name); auto uuid = imageUuid(header); std::string kind;
			if (uuid.empty()) { exclusions.insert("unidentified-image"); }
			bool systemPath = llvm::StringRef(path).starts_with("/usr/lib/") || llvm::StringRef(path).starts_with("/System/Library/");
			if (systemPath && (header->flags & MH_DYLIB_IN_CACHE) && _dyld_shared_cache_contains_path(name)) { kind = "system-shared-cache"; }
			else {
				llvm::SmallString<256> resolved;
				if (!llvm::sys::fs::real_path(path, resolved) && immutableStorePath(path) && immutableStorePath(resolved)) { path = resolved.str().str(); kind = "immutable-nix-store"; }
				else { kind = "unqualified"; exclusions.insert("mutable-or-unqualified-image:" + path); }
			}
			images.push_back({kind, path, uuid});
		}
		if (count != _dyld_image_count()) { exclusions.insert("runtime-changed"); }
#else
		exclusions.insert("unsupported-runtime-host");
#endif
		std::sort(images.begin(), images.end()); llvm::json::Array rows, reasons;
		for (const auto& image : images) { llvm::json::Array row; for (const auto& value : image) { row.push_back(value); } rows.push_back(std::move(row)); }
		for (const auto& reason : exclusions) { reasons.push_back(reason); }
		return llvm::json::Object{{"supported", exclusions.empty()}, {"images", std::move(rows)}, {"exclusions", std::move(reasons)}};
	}
};

// Effective compiler inputs; filesystem, runtime and storage admission are
// independent obligations of a reusable SDK response.
class NativeHeaderInputs {
	llvm::json::Array invocations;
	std::set<std::string> exclusions;
	std::string environment;
	llvm::json::Array requestArguments;
	std::string dependencyDiagnosticDigest;
	int readerExit = -1;
	llvm::json::Value runtimeBefore;

	static std::string digest(llvm::StringRef value) {
		llvm::SHA256 hash; hash.update(value); auto bytes = hash.final();
		static const char alphabet[] = "0123456789abcdef";
		std::string result;
		for (auto byte : bytes) { result.push_back(alphabet[byte >> 4]); result.push_back(alphabet[byte & 15]); }
		return result;
	}
public:
	explicit NativeHeaderInputs(const llvm::json::Value* runtime = nullptr) : runtimeBefore(runtime ? *runtime : llvm::json::Value(NativeRuntimeInputs::capture())) {
		std::vector<std::string> values;
#if defined(__APPLE__)
		char** entries = *_NSGetEnviron();
#elif defined(_WIN32)
		char** entries = _environ;
#else
		char** entries = environ;
#endif
		for (auto entry = entries; *entry; ++entry) { values.emplace_back(*entry); }
		std::set<std::string> names;
		for (const auto& value : values) {
			auto separator = value.find('=');
			if (separator == std::string::npos || !names.insert(value.substr(0, separator)).second) { reject("ambiguous-environment"); }
		}
		std::sort(values.begin(), values.end());
		std::string encoded;
		for (const auto& value : values) { encoded += std::to_string(value.size()) + ":" + value; }
		environment = digest(encoded);
	}
	void completed(int status) { readerExit = status; }
	void request(const std::vector<std::string>& arguments, llvm::StringRef dependencyDiagnostics) {
		for (const auto& argument : arguments) { requestArguments.push_back(argument); }
		dependencyDiagnosticDigest = digest(dependencyDiagnostics);
	}
	void reject(const std::string& reason) { exclusions.insert(reason); }
	void invocation(const clang::CompilerInvocation& value, clang::FileManager& files, bool preprocessing = false) {
		llvm::json::Array command;
		value.generateCC1CommandLine([&](const llvm::Twine& argument) {
			auto text = argument.str();
			if (!llvm::json::isUTF8(text)) { reject("non-utf8-argument"); text = llvm::json::fixUTF8(text); }
			command.push_back(std::move(text));
		});
		auto cwd = files.getVirtualFileSystem().getCurrentWorkingDirectory();
		if (!cwd) { reject("unavailable-invocation-cwd"); }
		invocations.push_back(llvm::json::Array{cwd ? *cwd : "", std::move(command)});
		const auto& language = value.getLangOpts();
		const auto& headers = value.getHeaderSearchOpts();
		const auto& preprocessor = value.getPreprocessorOpts();
		const auto& frontend = value.getFrontendOpts();
		const auto& diagnostics = value.getDiagnosticOpts();
		const auto& dependencies = value.getDependencyOutputOpts();
		// Files outside the traced source/header contract retain fresh extraction.
		if (language.Modules || language.CPlusPlusModules ||
			!frontend.ModuleFiles.empty() || !frontend.ModuleMapFiles.empty() ||
			!frontend.ModuleFileExtensions.empty() || !frontend.OriginalModuleMap.empty() ||
			!headers.PrebuiltModuleFiles.empty() || !headers.PrebuiltModulePaths.empty()) {
			reject("modules");
		}
		if (!preprocessor.ImplicitPCHInclude.empty() || !preprocessor.ChainedIncludes.empty() ||
			preprocessor.PrecompiledPreambleBytes.first || !preprocessor.PCHThroughHeader.empty() ||
			preprocessor.PCHWithHdrStop || preprocessor.PCHWithHdrStopCreate || preprocessor.GeneratePreamble) {
			reject("precompiled-header");
		}
		if (!frontend.ASTMergeFiles.empty()) { reject("serialized-ast"); }
		for (const auto& input : frontend.Inputs) {
			if (input.getKind().getFormat() != clang::InputKind::Source || input.getKind().isHeaderUnit()) {
				reject("serialized-or-module-input");
			}
			if (input.isBuffer() || (input.isFile() && input.getFile() == "-")) { reject("virtual-inputs"); }
		}
		if (!headers.VFSOverlayFiles.empty() || !preprocessor.RemappedFiles.empty() || !preprocessor.RemappedFileBuffers.empty()) { reject("virtual-inputs"); }
		if (!frontend.Plugins.empty() || !frontend.AddPluginActions.empty() || !frontend.PluginArgs.empty() || !frontend.ActionName.empty()) { reject("plugins"); }
		if (!frontend.OverrideRecordLayoutsFile.empty()) { reject("external-record-layout"); }
		if (language.APINotes || language.APINotesModules || !value.getAPINotesOpts().ModuleSearchPaths.empty()) { reject("external-api-notes"); }
		if (!language.NoSanitizeFiles.empty() || !language.XRayAlwaysInstrumentFiles.empty() ||
			!language.XRayNeverInstrumentFiles.empty() || !language.XRayAttrListFiles.empty() ||
			!language.ProfileListFiles.empty() || !language.OMPHostIRFile.empty()) {
			reject("external-instrumentation-inputs");
		}
		if (!diagnostics.DiagnosticSuppressionMappingsFile.empty()) { reject("diagnostic-suppression-input"); }
		if (!diagnostics.DiagnosticLogFile.empty() || !diagnostics.DiagnosticSerializationFile.empty()) { reject("diagnostic-file-output"); }
		if ((!preprocessing && (!dependencies.OutputFile.empty() || !dependencies.HeaderIncludeOutputFile.empty())) ||
			!dependencies.DOTOutputFile.empty() || !dependencies.ModuleDependencyOutputDir.empty()) {
			reject("dependency-file-output");
		}
		// Observational output and requested side files cannot be replayed as if
		// this invocation had run the work they describe.
		if (frontend.ShowStats || frontend.AppendStats || !frontend.StatsFile.empty() ||
			!frontend.TimeTracePath.empty() || value.getCodeGenOpts().TimePasses) { reject("performance-output"); }
		if (frontend.EmitSymbolGraph || !frontend.SymbolGraphOutputDir.empty() ||
			!frontend.ModuleOutputPath.empty() || !frontend.DumpMinimizationHintsPath.empty()) {
			reject("frontend-file-output");
		}
		if (frontend.ProgramAction != (preprocessing ? clang::frontend::PrintPreprocessedInput : clang::frontend::ParseSyntaxOnly) ||
			(!preprocessing && !frontend.OutputFile.empty()) || !frontend.CodeCompletionAt.FileName.empty()) { reject("alternate-frontend-action"); }
		if (!frontend.LLVMArgs.empty() || !frontend.MLIRArgs.empty()) { reject("experimental-options"); }

	}
	void macro(const clang::Token& token, const clang::MacroDefinition& definition) {
		const auto* info = definition.getMacroInfo();
		const auto* name = token.getIdentifierInfo();
		if (!info || !info->isBuiltinMacro() || !name) { return; }
		if (name->getName() == "__TIME__" || name->getName() == "__DATE__" || name->getName() == "__TIMESTAMP__") { reject("volatile-macro:" + name->getName().str()); }
	}
	llvm::json::Object report(const llvm::json::Array& selections, const llvm::json::Value* runtime = nullptr) {
		auto cwd = llvm::vfs::getRealFileSystem()->getCurrentWorkingDirectory();
		if (!cwd) { reject("unavailable-cwd"); }
		if (invocations.size() != 1) { reject("invocation-count"); }
		llvm::json::Array identity{"btrc.native-inputs.diagnostic.v2", llvm::json::Array(invocations), environment, cwd ? *cwd : "", llvm::json::Array(selections), *runtimeBefore.getAsObject()->get("images"), llvm::json::Array(requestArguments), dependencyDiagnosticDigest};
		auto serialized = llvm::formatv("{0}", llvm::json::Value(llvm::json::Array(identity))).str();
		llvm::json::Array reasons; for (const auto& reason : exclusions) { reasons.push_back(reason); }
		llvm::json::Object result{{"identity", std::move(identity)}, {"identity_sha256", digest(serialized)}, {"eligible_inputs", exclusions.empty()}, {"exclusions", std::move(reasons)}};
		llvm::json::Value runtimeAfter(runtime ? *runtime : llvm::json::Value(NativeRuntimeInputs::capture()));
		result["reader_exit"] = readerExit;
		result["runtime_before"] = runtimeBefore; result["runtime_after"] = runtimeAfter;
		result["runtime_stable"] = runtimeBefore == runtimeAfter;
		result["eligible_runtime"] = runtimeBefore.getAsObject()->getBoolean("supported").value_or(false) && runtimeBefore == runtimeAfter;
		return result;
	}
	bool write(llvm::StringRef path, const llvm::json::Array& selections) {
		std::error_code error; llvm::raw_fd_ostream output(path, error);
		if (error) { return false; }
		output << llvm::formatv("{0:2}\n", llvm::json::Value(report(selections))); output.close(); return !output.has_error();
	}
};

class NativeHeaderInputCallbacks : public clang::PPCallbacks {
	NativeHeaderInputs& inputs;
public:
	explicit NativeHeaderInputCallbacks(NativeHeaderInputs& value) : inputs(value) {}
	void MacroExpands(const clang::Token& token, const clang::MacroDefinition& definition, clang::SourceRange, const clang::MacroArgs*) override { inputs.macro(token, definition); }
};

class NativeHeaderConsumer : public clang::ASTConsumer {
	NativeHeaderRequests& requests;

public:
	explicit NativeHeaderConsumer(NativeHeaderRequests& value) : requests(value) {}
	void HandleTranslationUnit(clang::ASTContext& context) override { requests.read(context); }
};

class NativeHeaderAction : public clang::ASTFrontendAction {
	NativeHeaderRequests& requests;
	NativeHeaderInputs* inputs;

public:
	NativeHeaderAction(NativeHeaderRequests& value, NativeHeaderInputs* observations) : requests(value), inputs(observations) {}
	bool BeginSourceFileAction(clang::CompilerInstance& compiler) override {
		if (inputs) { compiler.getPreprocessor().addPPCallbacks(std::make_unique<NativeHeaderInputCallbacks>(*inputs)); }
		return true;
	}
	void EndSourceFileAction() override {
		if (inputs && getCompilerInstance().getDiagnostics().getNumWarnings()) { inputs->reject("diagnostics"); }
	}
	std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance&, llvm::StringRef) override { return std::make_unique<NativeHeaderConsumer>(requests); }
};

class NativeHeaderActionFactory : public clang::tooling::FrontendActionFactory {
	bool prepareOnly;
	NativeHeaderRequests& requests;
	NativeHeaderInputs* inputs;

public:
	NativeHeaderActionFactory(NativeHeaderRequests& value, NativeHeaderInputs* observations = nullptr, bool prepare = false) : prepareOnly(prepare), requests(value), inputs(observations) {}
	bool runInvocation(std::shared_ptr<clang::CompilerInvocation> invocation, clang::FileManager* files, std::shared_ptr<clang::PCHContainerOperations> pch, clang::DiagnosticConsumer* diagnostics) override {
		if (inputs) { inputs->invocation(*invocation, *files); }
		if (prepareOnly) { return true; }
		return clang::tooling::FrontendActionFactory::runInvocation(std::move(invocation), files, std::move(pch), diagnostics);
	}
	std::unique_ptr<clang::FrontendAction> create() override { return std::make_unique<NativeHeaderAction>(requests, inputs); }
};

// Record every filesystem answer consumed by Clang, including negative lookups.
// Installed only for requests that explicitly ask for a filesystem witness.
class NativeFileTrace {
public:
	llvm::json::Array rows;
	bool complete = true;
	static llvm::json::Object error(std::error_code ec) {
		return llvm::json::Object{{"code", ec.value()}, {"category", ec.category().name()}};
	}
	static llvm::json::Object status(const llvm::vfs::Status& value) {
		return llvm::json::Object{{"name", value.getName().str()}, {"device", (int64_t)value.getUniqueID().getDevice()},
			{"file", (int64_t)value.getUniqueID().getFile()}, {"type", (int64_t)value.getType()},
			{"permissions", (int64_t)value.getPermissions()}, {"size", (int64_t)value.getSize()},
			{"mtime", (int64_t)value.getLastModificationTime().time_since_epoch().count()},
			{"user", (int64_t)value.getUser()}, {"group", (int64_t)value.getGroup()}};
	}
	static llvm::vfs::Status directoryIdentity(const llvm::vfs::Status& value) {
		return llvm::vfs::Status(value.getName(), value.getUniqueID(), llvm::sys::TimePoint<>(), value.getUser(), value.getGroup(),
			0, value.getType(), value.getPermissions());
	}
	void stat(const char* operation, llvm::StringRef path, const llvm::ErrorOr<llvm::vfs::Status>& result) {
		llvm::json::Object row{{"operation", operation}, {"path", path.str()}};
		if (result) { row["status"] = status(*result); } else { row["error"] = error(result.getError()); }
		rows.push_back(std::move(row));
	}
	static std::string digest(llvm::StringRef bytes) {
#if defined(__APPLE__)
		std::array<uint8_t, CC_SHA256_DIGEST_LENGTH> value;
		CC_SHA256_CTX context;
		CC_SHA256_Init(&context);
		// Bound each update independently of size_t and CommonCrypto's CC_LONG.
		// Real source/header fixtures exercise multiple updates at this size.
		while (!bytes.empty()) {
			auto count = std::min<size_t>(bytes.size(), 65536);
			CC_SHA256_Update(&context, bytes.data(), static_cast<CC_LONG>(count));
			bytes = bytes.drop_front(count);
		}
		CC_SHA256_Final(value.data(), &context);
#else
		llvm::SHA256 hash; hash.update(bytes); auto value = hash.final();
#endif
		static const char alphabet[] = "0123456789abcdef";
		std::string hex;
		for (uint8_t byte : value) { hex.push_back(alphabet[byte >> 4]); hex.push_back(alphabet[byte & 15]); }
		return hex;
	}
	bool write(llvm::StringRef path) {
		std::error_code ec; llvm::raw_fd_ostream file(path, ec);
		if (ec) { llvm::errs() << ec.message() << '\n'; return false; }
		file << llvm::formatv("{0:2}\n", llvm::json::Value(llvm::json::Object{{"complete", complete}, {"operations", std::move(rows)}}));
		file.close(); return !file.has_error();
	}
};

class NativeTracedFile : public llvm::vfs::File {
	std::unique_ptr<llvm::vfs::File> file;
	NativeFileTrace& trace;
	std::string path;
	std::string openCwd;
	bool binary;

	void context(llvm::json::Object& row) const { row["open_cwd"] = openCwd; row["binary"] = binary; }
protected:
	void setPath(const llvm::Twine& value) override {
		// Preserve VFS behavior, but remapped handles need a richer witness.
		trace.complete = false;
		auto renamed = llvm::vfs::File::getWithPath(std::move(file), value);
		file = std::move(*renamed);
	}
public:
	NativeTracedFile(std::unique_ptr<llvm::vfs::File> value, NativeFileTrace& observations, std::string name, std::string cwd, bool isBinary)
		: file(std::move(value)), trace(observations), path(std::move(name)), openCwd(std::move(cwd)), binary(isBinary) {}
	llvm::ErrorOr<llvm::vfs::Status> status() override {
		auto result = file->status(); trace.stat("file-status", path, result); context(*trace.rows.back().getAsObject()); return result;
	}
	llvm::ErrorOr<std::string> getName() override {
		auto result = file->getName();
		llvm::json::Object row{{"operation", "file-name"}, {"path", path}};
		if (result) { row["name"] = *result; } else { row["error"] = NativeFileTrace::error(result.getError()); }
		context(row); trace.rows.push_back(std::move(row)); return result;
	}
	llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> getBuffer(const llvm::Twine& name, int64_t size = -1, bool nul = true, bool volatileFile = false) override {
		auto before = file->status();
		auto result = file->getBuffer(name, size, nul, volatileFile);
		// The bytes hashed here must be the exact bytes Clang later parses.
		// An mmap can change after this method returns, even after both stats.
		if (result) {
			result = llvm::MemoryBuffer::getMemBufferCopy((*result)->getBuffer(), (*result)->getBufferIdentifier());
		}
		auto after = file->status();
		llvm::json::Object row{{"operation", "buffer"}, {"path", path}, {"name", name.str()}, {"requested_size", size}, {"nul", nul}, {"volatile", volatileFile}};
		if (result) { row["bytes"] = (int64_t)(*result)->getBufferSize(); row["sha256"] = NativeFileTrace::digest((*result)->getBuffer()); }
		else { row["error"] = NativeFileTrace::error(result.getError()); }
		context(row);
		if (before && after && before->isRegularFile() && after->isRegularFile()) {
			row["before"] = NativeFileTrace::status(*before); row["after"] = NativeFileTrace::status(*after);
			if (*row.get("before") != *row.get("after")) { trace.complete = false; }
		} else { trace.complete = false; }
		trace.rows.push_back(std::move(row)); return result;
	}
	std::error_code close() override { return file->close(); }
};

class NativeTracedFileSystem : public llvm::vfs::ProxyFileSystem {
	NativeFileTrace& trace;
	bool directoryIdentity;
public:
	NativeTracedFileSystem(llvm::IntrusiveRefCntPtr<llvm::vfs::FileSystem> fs, NativeFileTrace& observations, bool stableDirectories = false)
		: llvm::vfs::ProxyFileSystem(std::move(fs)), trace(observations), directoryIdentity(stableDirectories) {}
	llvm::ErrorOr<llvm::vfs::Status> status(const llvm::Twine& path) override {
		auto result = getUnderlyingFS().status(path);
		// The admitted preprocessing mode uses DirectoryEntry identity, not
		// directory size/mtime. It excludes modules and directory enumeration.
		// Return and record the same view; each child lookup is still observed.
		if (directoryIdentity && result && result->isDirectory()) {
			result = NativeFileTrace::directoryIdentity(*result);
			trace.stat("directory-status", path.str(), result);
		} else { trace.stat("status", path.str(), result); }
		return result;
	}
	llvm::ErrorOr<std::unique_ptr<llvm::vfs::File>> openFileForRead(const llvm::Twine& path) override {
		auto cwd = getUnderlyingFS().getCurrentWorkingDirectory();
		if (!cwd) { trace.complete = false; }
		auto result = getUnderlyingFS().openFileForRead(path);
		llvm::json::Object row{{"operation", "open"}, {"path", path.str()}};
		if (!result) { row["error"] = NativeFileTrace::error(result.getError()); }
		trace.rows.push_back(std::move(row));
		if (!result) { return result.getError(); }
		return std::unique_ptr<llvm::vfs::File>(new NativeTracedFile(std::move(*result), trace, path.str(), cwd ? *cwd : "", false));
	}
	llvm::ErrorOr<std::unique_ptr<llvm::vfs::File>> openFileForReadBinary(const llvm::Twine& path) override {
		auto cwd = getUnderlyingFS().getCurrentWorkingDirectory();
		if (!cwd) { trace.complete = false; }
		auto result = getUnderlyingFS().openFileForReadBinary(path);
		llvm::json::Object row{{"operation", "open-binary"}, {"path", path.str()}};
		if (!result) { row["error"] = NativeFileTrace::error(result.getError()); }
		trace.rows.push_back(std::move(row));
		if (!result) { return result.getError(); }
		return std::unique_ptr<llvm::vfs::File>(new NativeTracedFile(std::move(*result), trace, path.str(), cwd ? *cwd : "", true));
	}
	bool exists(const llvm::Twine& path) override {
		bool result = getUnderlyingFS().exists(path);
		trace.rows.push_back(llvm::json::Object{{"operation", "exists"}, {"path", path.str()}, {"exists", result}}); return result;
	}
	std::error_code getRealPath(const llvm::Twine& path, llvm::SmallVectorImpl<char>& output) override {
		auto ec = getUnderlyingFS().getRealPath(path, output);
		trace.rows.push_back(llvm::json::Object{{"operation", "realpath"}, {"path", path.str()}, {"error", NativeFileTrace::error(ec)}, {"result", llvm::StringRef(output.data(), output.size()).str()}}); return ec;
	}
	std::error_code isLocal(const llvm::Twine& path, bool& local) override {
		auto ec = getUnderlyingFS().isLocal(path, local);
		llvm::json::Object row{{"operation", "local"}, {"path", path.str()}, {"error", NativeFileTrace::error(ec)}};
		if (!ec) { row["local"] = local; }
		trace.rows.push_back(std::move(row)); return ec;
	}
	llvm::ErrorOr<std::string> getCurrentWorkingDirectory() const override {
		auto result = getUnderlyingFS().getCurrentWorkingDirectory();
		llvm::json::Object row{{"operation", "getcwd"}};
		if (result) { row["directory"] = *result; } else { row["error"] = NativeFileTrace::error(result.getError()); }
		trace.rows.push_back(std::move(row)); return result;
	}
	std::error_code setCurrentWorkingDirectory(const llvm::Twine& path) override {
		auto ec = getUnderlyingFS().setCurrentWorkingDirectory(path);
		trace.rows.push_back(llvm::json::Object{{"operation", "setcwd"}, {"path", path.str()}, {"error", NativeFileTrace::error(ec)}}); return ec;
	}
	llvm::vfs::directory_iterator dir_begin(const llvm::Twine& path, std::error_code& ec) override {
		auto result = getUnderlyingFS().dir_begin(path, ec); trace.complete = false;
		trace.rows.push_back(llvm::json::Object{{"operation", "unrecorded-directory-iteration"}, {"path", path.str()}, {"error", NativeFileTrace::error(ec)}}); return result;
	}
};


class NativeHeaderDependencies {
	std::string diagnostic;
public:
	const std::string& diagnostics() const { return diagnostic; }
	bool resolve(const std::vector<std::string>& packages, std::vector<std::string>& flags, bool captureDiagnostics = false) {
		if (packages.empty()) { return true; }
		auto executable = llvm::sys::findProgramByName("pkg-config");
		if (!executable) { llvm::errs() << "error: native imports require pkg-config: " << executable.getError().message() << '\n'; return false; }
		llvm::SmallString<128> output;
		if (auto error = llvm::sys::fs::createTemporaryFile("btrc-native-cflags", "txt", output)) {
			llvm::errs() << "error: cannot capture pkg-config flags: " << error.message() << '\n';
			return false;
		}
		llvm::FileRemover cleanup(output);
		llvm::SmallString<128> errorOutput;
		if (auto error = captureDiagnostics ? llvm::sys::fs::createTemporaryFile("btrc-native-cflags", "stderr", errorOutput) : std::error_code()) {
			llvm::errs() << "error: cannot capture pkg-config diagnostics: " << error.message() << '\n'; return false;
		}
		llvm::FileRemover errorCleanup(errorOutput, captureDiagnostics);
		llvm::SmallVector<llvm::StringRef> arguments{*executable, "--cflags", "--"};
		for (const auto& package : packages) { arguments.push_back(package); }
		std::optional<llvm::StringRef> redirects[] = {llvm::StringRef(""), output.str(), captureDiagnostics ? std::optional<llvm::StringRef>(errorOutput.str()) : std::nullopt};
		std::string error;
		int status = llvm::sys::ExecuteAndWait(*executable, arguments, std::nullopt, redirects, 30, 0, &error);
		if (captureDiagnostics) {
			auto diagnostics = llvm::MemoryBuffer::getFile(errorOutput);
			if (!diagnostics) { llvm::errs() << "error: cannot read pkg-config diagnostics\n"; return false; }
			diagnostic = (*diagnostics)->getBuffer().str(); llvm::errs() << diagnostic;
		}
		if (status != 0) {
			llvm::errs() << "error: pkg-config --cflags failed";
			for (const auto& package : packages) { llvm::errs() << " " << package; }
			llvm::errs() << ": " << error << '\n';
			return false;
		}
		auto content = llvm::MemoryBuffer::getFile(output);
		if (!content) { llvm::errs() << "error: cannot read pkg-config flags: " << content.getError().message() << '\n'; return false; }
		if ((*content)->getBuffer().contains('\0')) { llvm::errs() << "error: pkg-config flags contain NUL\n"; return false; }
		llvm::BumpPtrAllocator allocator;
		llvm::StringSaver saver(allocator);
		llvm::SmallVector<const char*> tokens;
		llvm::cl::TokenizeGNUCommandLine((*content)->getBuffer(), saver, tokens);
		for (const auto* token : tokens) { flags.emplace_back(token); }
		return true;
	}
};

class NativeTraceVerifier {
	llvm::IntrusiveRefCntPtr<llvm::vfs::FileSystem> fs = llvm::vfs::getRealFileSystem();
	bool healthy = true;
	using Observations = std::unordered_multimap<std::string, llvm::json::Value>;
	Observations seen;
	static bool contains(const Observations& observations, const std::string& key, const llvm::json::Value& value) {
		auto range = observations.equal_range(key);
		return std::any_of(range.first, range.second, [&](const auto& entry) { return entry.second == value; });
	}
	bool sameError(const llvm::json::Object& row, std::error_code ec) {
		const auto* expected = row.get("error");
		return expected && *expected == llvm::json::Value(NativeFileTrace::error(ec));
	}
	bool observe(const llvm::json::Object& row) {
		auto operation = row.getString("operation").value_or("");
		auto path = row.getString("path").value_or("");
		if (operation == "directory-status") {
			auto status = fs->status(path);
			return status && status->isDirectory() && row.get("status") &&
				*row.get("status") == llvm::json::Value(NativeFileTrace::status(NativeFileTrace::directoryIdentity(*status)));
		}
		if (operation == "status") {
			auto status = fs->status(path);
			return status ? row.get("status") && *row.get("status") == llvm::json::Value(NativeFileTrace::status(*status)) : sameError(row, status.getError());
		}
		if (operation == "exists") { return row.getBoolean("exists") == fs->exists(path); }
		if (operation == "realpath") {
			llvm::SmallString<256> real; auto ec = fs->getRealPath(path, real);
			return sameError(row, ec) && (ec || row.getString("result") == real.str());
		}
		if (operation == "getcwd") {
			auto cwd = fs->getCurrentWorkingDirectory();
			return cwd ? row.getString("directory") == *cwd : sameError(row, cwd.getError());
		}
		if (operation == "setcwd") { return sameError(row, fs->setCurrentWorkingDirectory(path)); }
		if (operation == "local") {
			bool local = false; auto ec = fs->isLocal(path, local);
			return sameError(row, ec) && (ec || row.getBoolean("local") == local);
		}
		if (operation != "open" && operation != "open-binary" && operation != "file-name" && operation != "file-status" && operation != "buffer") { return false; }
		auto cwd = fs->getCurrentWorkingDirectory(); if (!cwd) { return false; }
		auto openCwd = row.getString("open_cwd");
		if (openCwd && fs->setCurrentWorkingDirectory(*openCwd)) { return false; }
		bool binary = operation == "open-binary" || row.getBoolean("binary").value_or(false);
		auto opened = binary ? fs->openFileForReadBinary(path) : fs->openFileForRead(path);
		if (openCwd && fs->setCurrentWorkingDirectory(*cwd)) { return false; }
		if (!opened) { return sameError(row, opened.getError()); }
		bool valid = false;
		if (operation == "open" || operation == "open-binary") { valid = !row.get("error"); }
		else if (operation == "file-status") {
			auto status = (*opened)->status();
			valid = status ? row.get("status") && *row.get("status") == llvm::json::Value(NativeFileTrace::status(*status)) : sameError(row, status.getError());
		} else if (operation == "file-name") {
			auto name = (*opened)->getName();
			valid = name ? row.getString("name") == *name : sameError(row, name.getError());
		} else {
			auto before = (*opened)->status();
			if (!before || !row.get("before") || *row.get("before") != llvm::json::Value(NativeFileTrace::status(*before))) { return false; }
			auto buffer = (*opened)->getBuffer(row.getString("name").value_or(path), row.getInteger("requested_size").value_or(-1), row.getBoolean("nul").value_or(true), row.getBoolean("volatile").value_or(false));
			auto after = (*opened)->status();
			if (!after || !row.get("after") || *row.get("after") != llvm::json::Value(NativeFileTrace::status(*after))) { return false; }
			if (buffer) {
				valid = row.getInteger("bytes") == (int64_t)(*buffer)->getBufferSize() && row.getString("sha256") == NativeFileTrace::digest((*buffer)->getBuffer());
			} else { valid = sameError(row, buffer.getError()); }
		}
		return !(*opened)->close() && valid;
	}
public:
	bool validate(const llvm::json::Value& document) {
		const auto* root = document.getAsObject();
		if (!root || root->getBoolean("complete") != true) { return false; }
		const auto* operations = root->getArray("operations");
		return operations && validate(std::vector<const llvm::json::Array*>{operations});
	}
	bool validate(const std::vector<const llvm::json::Array*>& fragments) {
		if (!healthy) { return false; }
		auto initialCwd = fs->getCurrentWorkingDirectory();
		if (!initialCwd) { return false; }
		auto restore = llvm::make_scope_exit([&] { if (fs->setCurrentWorkingDirectory(*initialCwd)) { healthy = false; } });
		// A failed group publishes no newly checked operations to other groups.
		Observations pending;
		for (const auto* operations : fragments) {
			for (const auto& value : *operations) {
				const auto* row = value.getAsObject(); if (!row) { return false; }
				auto operation = row->getString("operation").value_or("");
				auto path = row->getString("path").value_or("");
				auto openCwd = row->getString("open_cwd");
				// CWD changes are ordered state transitions, never deduplicated.
				bool shareable = operation != "setcwd" && operation != "getcwd";
				std::string directory;
				// Absolute paths do not depend on the current directory, unless the
				// recorded opening directory is relative. Keep that context bound.
				if (!shareable || !llvm::sys::path::is_absolute(path) || (openCwd && !llvm::sys::path::is_absolute(*openCwd))) {
					auto cwd = fs->getCurrentWorkingDirectory();
					if (!cwd) { return false; }
					directory = *cwd;
				}
				// Group candidates cheaply, but compare the complete recorded value.
				// Paths alone cannot prove matching status, bytes, errors or open CWD.
				std::string key;
				key.reserve(directory.size() + operation.size() + path.size() + 2);
				key.append(directory); key.push_back('\0');
				key.append(operation.data(), operation.size()); key.push_back('\0');
				key.append(path.data(), path.size());
				if (shareable && (contains(seen, key, value) || contains(pending, key, value))) { continue; }
				if (!observe(*row)) { return false; }
				if (shareable) { pending.emplace(std::move(key), value); }
			}
		}
		if (fs->setCurrentWorkingDirectory(*initialCwd)) { return false; }
		seen.merge(pending);
		return true;
	}
};


// Exact-cc1 preprocessing shares the SDK input policy and filesystem recorder.
// Output destinations belong to the capture stage, never to a cache identity.
class NativePreprocess {
	class Action : public clang::PrintPreprocessedAction {
		NativeHeaderInputs& inputs;
	public:
		explicit Action(NativeHeaderInputs& value) : inputs(value) {}
		bool BeginSourceFileAction(clang::CompilerInstance& compiler) override {
			compiler.getPreprocessor().addPPCallbacks(std::make_unique<NativeHeaderInputCallbacks>(inputs));
			return true;
		}
	};
	NativeFileTrace trace;
	llvm::IntrusiveRefCntPtr<llvm::vfs::FileSystem> fs;
	std::shared_ptr<clang::CompilerInvocation> invocation = std::make_shared<clang::CompilerInvocation>();
	std::string diagnostics;
	llvm::raw_string_ostream diagnosticStream{diagnostics};
	clang::CompilerInstance compiler{invocation};
	NativeHeaderInputs inputs;
	llvm::json::Object prepared;
	bool ready = false;
public:
	NativePreprocess(const std::vector<std::string>& arguments, const llvm::json::Object& context) {
		if (context.getBoolean("eligible") != true || arguments.size() < 3 || arguments[1] != "-cc1") { return; }
		llvm::SmallString<256> actual;
		if (llvm::sys::fs::real_path(arguments[0], actual) || context.getString("compiler") != actual.str()) { return; }
		fs = llvm::makeIntrusiveRefCnt<NativeTracedFileSystem>(llvm::vfs::getRealFileSystem(), trace, true);
		compiler.createDiagnostics(*fs, new clang::TextDiagnosticPrinter(diagnosticStream, invocation->getDiagnosticOpts()), true);
		compiler.setVerboseOutputStream(diagnosticStream);
		llvm::SmallVector<const char*> options;
		for (size_t i = 2; i < arguments.size(); ++i) { options.push_back(arguments[i].c_str()); }
		if (!clang::CompilerInvocation::CreateFromArgs(*invocation, options, compiler.getDiagnostics(), arguments[0].c_str()) || !diagnostics.empty()) { return; }
		auto& frontend = invocation->getFrontendOpts();
		auto& dependencies = invocation->getDependencyOutputOpts();
		if (frontend.ShowHelp || frontend.ShowVersion || frontend.Inputs.size() != 1 || frontend.OutputFile.empty() || frontend.OutputFile == "-" ||
			dependencies.OutputFile.empty() || dependencies.OutputFile == "-" || dependencies.HeaderIncludeOutputFile.empty() ||
			dependencies.HeaderIncludeOutputFile == "-") { return; }
		frontend.OutputFile = "<btrc-preprocessed>";
		dependencies.OutputFile = "<btrc-dependencies>";
		dependencies.HeaderIncludeOutputFile = "<btrc-headers>";
		compiler.createFileManager(fs); compiler.createSourceManager(compiler.getFileManager());
		inputs.request({"btrc.native-preprocess.v1", context.getString("identity_sha256")->str()}, "");
		inputs.invocation(*invocation, compiler.getFileManager(), true);
		prepared = inputs.report(llvm::json::Array());
		ready = prepared.getBoolean("eligible_inputs") == true && prepared.getBoolean("eligible_runtime") == true;
	}
	bool valid() const { return ready; }
	const llvm::json::Object& contract() const { return prepared; }
	const std::string& errors() const { return diagnostics; }
	bool run(const std::string& directory, llvm::json::Object& contract, llvm::json::Object& filesystem, llvm::json::Array& buffers) {
		if (!ready) { return false; }
		invocation->getFrontendOpts().OutputFile = directory + "preprocessed";
		invocation->getDependencyOutputOpts().OutputFile = directory + "dependencies";
		invocation->getDependencyOutputOpts().HeaderIncludeOutputFile = directory + "headers";
		// Diagnostic mappings affect __has_extension and must precede preprocessing.
		clang::ProcessWarningOptions(compiler.getDiagnostics(), compiler.getDiagnosticOpts(), *fs);
		Action action(inputs);
		bool passed = compiler.ExecuteAction(action);
		inputs.completed(passed ? 0 : 1);
		contract = inputs.report(llvm::json::Array());
		if (!passed || contract.getBoolean("eligible_inputs") != true || contract.getBoolean("eligible_runtime") != true || !trace.complete) { return false; }
		auto cwd = llvm::vfs::getRealFileSystem()->getCurrentWorkingDirectory();
		if (!cwd) { return false; }
		// Compact only identical observations under one proven working directory.
		std::set<std::string> seen, content;
		llvm::json::Array rows;
		for (const auto& value : trace.rows) {
			const auto* row = value.getAsObject(); if (!row) { return false; }
			auto operation = row->getString("operation");
			if (!operation || *operation == "setcwd" || (*operation == "getcwd" && row->getString("directory") != *cwd) ||
				(row->get("open_cwd") && row->getString("open_cwd") != *cwd)) { return false; }
			auto encoded = llvm::formatv("{0}", value).str();
			if (seen.insert(encoded).second) { rows.push_back(value); }
			if (*operation == "buffer") {
				auto path = row->getString("path"), digest = row->getString("sha256");
				if (!path || !digest) { return false; }
				llvm::json::Array buffer{path->str(), digest->str()};
				auto key = llvm::formatv("{0}", llvm::json::Value(llvm::json::Array(buffer))).str();
				if (content.insert(key).second) { buffers.push_back(std::move(buffer)); }
			}
		}
		filesystem = llvm::json::Object{{"complete", true}, {"operations", std::move(rows)}};
		return true;
	}
};

// A preprocessing receipt may borrow this reader's Clang implementation only
// when the selected tool comes from the configured provider and its actual
// loader images agree. Version banners and arbitrary immutable wrappers are
// insufficient: a wrapper can choose a different compiler for different modes.
class NativeCompilerContext {
	std::vector<std::string> drivers;
	std::vector<std::string> environment;
	llvm::json::Value runtime = nullptr;
	std::string compiler, rejection, environmentDigest;

	static std::string canonical(llvm::StringRef path) {
		llvm::SmallString<256> result;
		return !path.empty() && !llvm::sys::fs::real_path(path, result) ? result.str().str() : "";
	}
	static llvm::json::Object refused(llvm::StringRef reason) {
		return llvm::json::Object{{"schema", "btrc.native-compiler-context.v1"}, {"eligible", false}, {"reason", reason.str()}};
	}
public:
	explicit NativeCompilerContext(const std::vector<std::string>& selected, llvm::StringRef selectedCompiler = "") : drivers(selected) {
#if defined(__APPLE__) && defined(BTRC_NATIVE_CLANG_DRIVER) && defined(BTRC_NATIVE_CLANGXX_DRIVER) && defined(BTRC_NATIVE_CLANG_COMPILER) && defined(BTRC_NATIVE_CLANGXX_COMPILER)
		std::set<std::string> names;
		for (char** entry = *_NSGetEnviron(); *entry; ++entry) {
			llvm::StringRef value(*entry); auto name = value.take_until([](char c) { return c == '='; });
			if (name.empty() || !value.contains('=') || !names.insert(name.str()).second) { rejection = "ambiguous-environment"; return; }
			if (name.starts_with("DYLD_") || name.starts_with("BASH_FUNC_") || name == "BASH_ENV" || name == "ENV" ||
				name == "SHELLOPTS" || name == "BASHOPTS" || name == "BASH_XTRACEFD") { rejection = "dynamic-tool-environment"; return; }
			environment.push_back(value.str());
		}
		std::sort(environment.begin(), environment.end());
		llvm::json::Array values; for (const auto& value : environment) { values.push_back(value); }
		environmentDigest = NativeFileTrace::digest(llvm::formatv("{0}", llvm::json::Value(std::move(values))).str());
		std::set<std::string> configured;
		for (const auto* path : {BTRC_NATIVE_CLANG_DRIVER, BTRC_NATIVE_CLANGXX_DRIVER, BTRC_NATIVE_CLANG_COMPILER, BTRC_NATIVE_CLANGXX_COMPILER}) {
			auto resolved = canonical(path);
			if (resolved.empty() || !NativeRuntimeInputs::immutableStorePath(path) || !NativeRuntimeInputs::immutableStorePath(resolved)) {
				rejection = "unavailable-compiler-provider"; return;
			}
			configured.insert(std::move(resolved));
		}
		for (const auto& driver : drivers) {
			if (!NativeRuntimeInputs::immutableStorePath(driver) || !configured.count(canonical(driver))) { rejection = "unqualified-driver"; return; }
		}
		compiler = selectedCompiler.empty() ? canonical(BTRC_NATIVE_CLANG_COMPILER) : canonical(selectedCompiler);
		if ((!selectedCompiler.empty() && !NativeRuntimeInputs::immutableStorePath(selectedCompiler)) || compiler.empty() ||
			(compiler != canonical(BTRC_NATIVE_CLANG_COMPILER) && compiler != canonical(BTRC_NATIVE_CLANGXX_COMPILER))) {
			rejection = "unqualified-compiler"; return;
		}
		runtime = NativeRuntimeInputs::capture();
		if (runtime.getAsObject()->getBoolean("supported") != true) { rejection = "unsupported-runtime"; }
#else
		(void)selectedCompiler;
		rejection = "unsupported-compiler-provider";
#endif
	}
	bool valid() const { return rejection.empty(); }
	llvm::json::Object failure(llvm::StringRef reason = "") const { return refused(reason.empty() ? rejection : reason); }

	bool observe(const std::string& directory) const {
		if (!valid()) { return false; }
		std::vector<std::string> ownedEnvironment(environment); ownedEnvironment.push_back("DYLD_PRINT_LIBRARIES=1");
		llvm::SmallVector<llvm::StringRef> childEnvironment;
		for (const auto& value : ownedEnvironment) { childEnvironment.push_back(value); }
		std::string output = directory + "stdout", errors = directory + "stderr";
		std::optional<llvm::StringRef> redirects[] = {llvm::StringRef(""), output, errors};
		return llvm::sys::ExecuteAndWait(compiler, {compiler, "-cc1", "-version"}, childEnvironment, redirects, 10) == 0;
	}

	llvm::json::Object finish(llvm::StringRef version, llvm::StringRef trace) const {
#if defined(__APPLE__)
		if (!valid()) { return failure(); }
		if (runtime != llvm::json::Value(NativeRuntimeInputs::capture())) { return refused("helper-runtime-changed"); }
		std::set<std::vector<std::string>> expected, observed;
		const char* ownImage = _dyld_get_image_name(0);
		if (!ownImage) { return refused("unavailable-helper-image"); }
		auto ownPath = canonical(ownImage);
		const auto* images = runtime.getAsObject()->getArray("images");
		if (!images || ownPath.empty()) { return refused("unavailable-helper-images"); }
		bool clangImage = false, llvmImage = false;
		for (const auto& value : *images) {
			const auto* row = value.getAsArray();
			if (!row || row->size() != 3) { return refused("unavailable-helper-images"); }
			std::vector<std::string> fields;
			for (const auto& item : *row) {
				auto text = item.getAsString(); if (!text) { return refused("unavailable-helper-images"); } fields.push_back(text->str());
			}
			if (fields[1] == ownPath) { continue; }
			auto name = llvm::sys::path::filename(fields[1]);
			clangImage |= name.starts_with("libclang-cpp."); llvmImage |= name.starts_with("libLLVM.");
			expected.insert(std::move(fields));
		}
		if (!clangImage || !llvmImage) { return refused("unavailable-clang-runtime"); }
		llvm::Regex linePattern("^dyld\\[([0-9]+)\\]: <([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})> (/.+)$");
		llvm::Regex transitionPattern("^dyld\\[([0-9]+)\\]: move (loaded to delayed|delayed to loaded): (.+)$");
		llvm::SmallVector<llvm::StringRef> lines; trace.split(lines, '\n', -1, false);
		std::map<std::string, std::vector<std::string>> allImages;
		std::set<std::string> active;
		std::string process, compilerUuid;
		for (auto line : lines) {
			llvm::SmallVector<llvm::StringRef> matches;
			if (!linePattern.match(line, &matches)) {
				// dyld's diagnostic stream includes mapped images subsequently
				// deferred. _dyld_image_count reports only active images. Replay
				// these explicit transitions; unknown/ambiguous events refuse.
				if (!transitionPattern.match(line, &matches) || process.empty() || matches[1] != process) { return refused("unexpected-runtime-output"); }
				std::string path;
				for (const auto& image : allImages) {
					if (llvm::sys::path::filename(image.first) == matches[3]) {
						if (!path.empty()) { return refused("ambiguous-runtime-transition"); } path = image.first;
					}
				}
				if (path.empty()) { return refused("unknown-runtime-transition"); }
				if (matches[2] == "loaded to delayed") {
					if (!active.erase(path)) { return refused("invalid-runtime-transition"); }
				} else if (!active.insert(path).second) { return refused("invalid-runtime-transition"); }
				continue;
			}
			if (process.empty()) { process = matches[1].str(); }
			if (matches[1] != process) { return refused("multiple-runtime-processes"); }
			std::string uuid; for (char c : matches[2]) { if (c != '-') { uuid.push_back(llvm::toLower(c)); } }
			std::string path = matches[3].str(), kind;
			if (llvm::StringRef(path).starts_with("/nix/store/")) {
				path = canonical(path); if (path.empty() || !NativeRuntimeInputs::immutableStorePath(path)) { return refused("unqualified-compiler-image"); }
				kind = "immutable-nix-store";
			} else if ((llvm::StringRef(path).starts_with("/usr/lib/") || llvm::StringRef(path).starts_with("/System/Library/")) &&
				_dyld_shared_cache_contains_path(path.c_str())) { kind = "system-shared-cache"; }
			else { return refused("unqualified-compiler-image"); }
			if (!allImages.emplace(path, std::vector<std::string>{kind, path, uuid}).second) { return refused("duplicate-compiler-image"); }
			active.insert(path);
			if (path == compiler) { compilerUuid = uuid; }
		}
		for (const auto& path : active) { if (path != compiler) { observed.insert(allImages.at(path)); } }
		if (compilerUuid.empty() || !active.count(compiler) || observed != expected) { return refused("compiler-runtime-mismatch"); }
		llvm::json::Array tools, boundImages, mappedImages;
		for (const auto& driver : drivers) { tools.push_back(driver); }
		for (const auto& row : observed) { llvm::json::Array image; for (const auto& field : row) { image.push_back(field); } boundImages.push_back(std::move(image)); }
		for (const auto& row : allImages) { llvm::json::Array image; for (const auto& field : row.second) { image.push_back(field); } mappedImages.push_back(std::move(image)); }
		llvm::json::Array identity{"btrc.native-compiler-context.v1", llvm::json::Array(tools), compiler, compilerUuid,
			llvm::json::Array(boundImages), llvm::json::Array(mappedImages), runtime, environmentDigest, version.str()};
		std::string key = NativeFileTrace::digest(llvm::formatv("{0}", llvm::json::Value(llvm::json::Array(identity))).str());
		return llvm::json::Object{{"schema", "btrc.native-compiler-context.v1"}, {"eligible", true}, {"drivers", std::move(tools)},
			{"compiler", compiler}, {"images", std::move(boundImages)}, {"identity", std::move(identity)}, {"identity_sha256", key}};
#else
		(void)version; (void)trace;
		return refused("unsupported-compiler-provider");
#endif
	}
};

// Private, content-addressed response blobs with an atomically published receipt.
// Corruption, unsupported inputs and storage failures are cache misses.
#if !defined(_WIN32)
class NativeHeaderCache {
	int root = -1;
	std::string directory;
	NativeTraceVerifier verifier;
	struct TraceFragment { uint64_t bytes; llvm::json::Value rows; };
	std::map<std::string, TraceFragment> traceFragments;
	uint64_t fragmentBytes = 0;
	static constexpr uint64_t receiptLimit = 64 * 1024 * 1024;
	static constexpr uint64_t diagnosticLimit = 8 * 1024 * 1024;

	class Descriptor {
		int value;
	public:
		explicit Descriptor(int descriptor = -1) : value(descriptor) {}
		~Descriptor() { if (value >= 0) { ::close(value); } }
		Descriptor(const Descriptor&) = delete;
		Descriptor& operator=(const Descriptor&) = delete;
		int get() const { return value; }
		void reset(int descriptor) { if (value >= 0) { ::close(value); } value = descriptor; }
	};
	static bool hex(llvm::StringRef text) {
		return text.size() == 64 && std::all_of(text.begin(), text.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
	}
	// The shared directory lock covers creation/cleanup gaps. Each worker's
	// inherited lease outlives a killed parent, so collection cannot race a
	// still-running child. Only this private namespace is garbage-collected;
	// explicit session publication stages remain owned by their caller.
	class WorkerStage {
		Descriptor directory, stage, lease;
		std::string name, pathname;
		static bool privateDirectory(int descriptor) {
			struct stat status;
			return descriptor >= 0 && ::fstat(descriptor, &status) == 0 && S_ISDIR(status.st_mode) &&
				status.st_uid == ::geteuid() && (status.st_mode & 0777) == 0700;
		}
		static int openDirectory(int cache, bool create) {
			if (create && ::mkdirat(cache, "workers", 0700) != 0 && errno != EEXIST) { return -1; }
			int descriptor = ::openat(cache, "workers", O_RDONLY | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW);
			if (privateDirectory(descriptor)) { return descriptor; }
			if (descriptor >= 0) { ::close(descriptor); }
			return -1;
		}
		static void remove(int directory, int stage, const std::string& name) {
			// This leased, private worker namespace owns every capture, including
			// Clang's randomly named atomic-output temporary after an interruption.
			// Unlink entries without following symlinks or descending directories.
			int iterator = ::openat(stage, ".", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
			if (iterator < 0) { return; }
			DIR* entries = ::fdopendir(iterator);
			if (!entries) { ::close(iterator); return; }
			while (auto* entry = ::readdir(entries)) {
				llvm::StringRef file(entry->d_name);
				if (file != "." && file != "..") { ::unlinkat(stage, entry->d_name, 0); }
			}
			::closedir(entries);
			::unlinkat(directory, name.c_str(), AT_REMOVEDIR);
		}
	public:
		WorkerStage(int cache, const std::string& path) : directory(openDirectory(cache, true)) {
			if (directory.get() < 0 || ::flock(directory.get(), LOCK_SH) != 0) { return; }
			auto unlock = llvm::make_scope_exit([&] { ::flock(directory.get(), LOCK_UN); });
			for (int attempt = 0; attempt < 32; ++attempt) {
				auto tick = std::chrono::steady_clock::now().time_since_epoch().count();
				std::string candidate = NativeFileTrace::digest(std::to_string(::getpid()) + ":" + std::to_string(tick) + ":" + std::to_string(attempt));
				if (::mkdirat(directory.get(), candidate.c_str(), 0700) == 0) { name = candidate; break; }
				if (errno != EEXIST) { return; }
			}
			if (name.empty()) { return; }
			stage.reset(::openat(directory.get(), name.c_str(), O_RDONLY | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW));
			if (!privateDirectory(stage.get())) { stage.reset(-1); return; }
			// Deliberately inherited: a spawned child retains the lease if its
			// parent is killed before it finishes writing the captures.
			lease.reset(::openat(stage.get(), "owner", O_RDWR | O_NOFOLLOW | O_CREAT | O_EXCL, 0600));
			if (lease.get() < 0 || ::flock(lease.get(), LOCK_EX | LOCK_NB) != 0) { return; }
			pathname = path + "/workers/" + name + "/";
		}
		~WorkerStage() {
			if (name.empty() || directory.get() < 0 || ::flock(directory.get(), LOCK_SH) != 0) { return; }
			if (stage.get() >= 0) { remove(directory.get(), stage.get(), name); }
			else { ::unlinkat(directory.get(), name.c_str(), AT_REMOVEDIR); }
			::flock(directory.get(), LOCK_UN);
		}
		bool valid() const { return !pathname.empty(); }
		int get() const { return stage.get(); }
		const std::string& path() const { return pathname; }
		static void collect(int cache) {
			Descriptor directory(openDirectory(cache, false));
			if (directory.get() < 0 || ::flock(directory.get(), LOCK_EX | LOCK_NB) != 0) { return; }
			int iterator = ::openat(directory.get(), ".", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
			if (iterator < 0) { return; }
			DIR* entries = ::fdopendir(iterator);
			if (!entries) { ::close(iterator); return; }
			auto close = llvm::make_scope_exit([&] { ::closedir(entries); });
			unsigned candidates = 0;
			while (auto* entry = ::readdir(entries)) {
				if (!hex(entry->d_name)) { continue; }
				if (++candidates > 128) { break; }
				Descriptor stage(::openat(directory.get(), entry->d_name, O_RDONLY | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW));
				if (!privateDirectory(stage.get())) { continue; }
				Descriptor lease(::openat(stage.get(), "owner", O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
				if (lease.get() < 0) {
					if (errno == ENOENT) { remove(directory.get(), stage.get(), entry->d_name); }
					continue;
				}
				struct stat status;
				if (!file(lease.get(), 0, status) || ::flock(lease.get(), LOCK_EX | LOCK_NB) != 0) { continue; }
				remove(directory.get(), stage.get(), entry->d_name);
			}
		}
	};
	static bool file(int descriptor, uint64_t limit, struct stat& status) {
		return descriptor >= 0 && ::fstat(descriptor, &status) == 0 && S_ISREG(status.st_mode) &&
			status.st_uid == ::geteuid() && (status.st_mode & 0777) == 0600 && status.st_nlink == 1 &&
			status.st_size >= 0 && static_cast<uint64_t>(status.st_size) <= limit;
	}
	static bool same(const struct stat& a, const struct stat& b) {
#if defined(__APPLE__)
		bool times = a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec &&
			a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec;
#else
		bool times = a.st_mtim.tv_sec == b.st_mtim.tv_sec && a.st_mtim.tv_nsec == b.st_mtim.tv_nsec &&
			a.st_ctim.tv_sec == b.st_ctim.tv_sec && a.st_ctim.tv_nsec == b.st_ctim.tv_nsec;
#endif
		return times && a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_size == b.st_size &&
			a.st_mode == b.st_mode && a.st_uid == b.st_uid && a.st_gid == b.st_gid && a.st_nlink == b.st_nlink;
	}
	static bool read(int parent, llvm::StringRef name, uint64_t limit, std::string& output) {
		Descriptor descriptor(::openat(parent, name.str().c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
		struct stat before, after;
		if (!file(descriptor.get(), limit, before)) { return false; }
		output.resize(static_cast<size_t>(before.st_size)); size_t position = 0;
		while (position < output.size()) {
			ssize_t size = ::read(descriptor.get(), output.data() + position, output.size() - position);
			if (size < 0 && errno == EINTR) { continue; }
			if (size <= 0) { return false; } position += static_cast<size_t>(size);
		}
		return ::fstat(descriptor.get(), &after) == 0 && same(before, after);
	}
	static bool write(int descriptor, llvm::StringRef bytes) {
		while (!bytes.empty()) {
			ssize_t size = ::write(descriptor, bytes.data(), bytes.size());
			if (size < 0 && errno == EINTR) { continue; }
			if (size <= 0) { return false; } bytes = bytes.drop_front(static_cast<size_t>(size));
		}
		return true;
	}
	int temporary(std::string& name) {
		if (::flock(root, LOCK_SH) != 0) { return -1; }
		auto unlock = llvm::make_scope_exit([&] { ::flock(root, LOCK_UN); });
		for (int attempt = 0; attempt < 32; ++attempt) {
			auto tick = std::chrono::steady_clock::now().time_since_epoch().count();
			name = ".tmp-" + NativeFileTrace::digest(std::to_string(::getpid()) + ":" + std::to_string(tick) + ":" + std::to_string(attempt));
			int descriptor = ::openat(root, name.c_str(), O_WRONLY | O_CLOEXEC | O_NOFOLLOW | O_CREAT | O_EXCL, 0600);
			if (descriptor >= 0) {
				if (::flock(descriptor, LOCK_EX | LOCK_NB) == 0) { return descriptor; }
				::close(descriptor); ::unlinkat(root, name.c_str(), 0); return -1;
			}
			if (errno != EEXIST) { return -1; }
		}
		return -1;
	}
	void collectTemporaryFiles() {
		if (::flock(root, LOCK_EX | LOCK_NB) != 0) { return; }
		auto unlock = llvm::make_scope_exit([&] { ::flock(root, LOCK_UN); });
		int iterator = ::openat(root, ".", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
		if (iterator < 0) { return; }
		DIR* entries = ::fdopendir(iterator);
		if (!entries) { ::close(iterator); return; }
		auto close = llvm::make_scope_exit([&] { ::closedir(entries); });
		unsigned candidates = 0;
		while (auto* entry = ::readdir(entries)) {
			llvm::StringRef name(entry->d_name);
			if (!name.starts_with(".tmp-") || !hex(name.drop_front(5))) { continue; }
			if (++candidates > 128) { break; }
			Descriptor fileDescriptor(::openat(root, entry->d_name, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
			struct stat status;
			if (!file(fileDescriptor.get(), UINT64_MAX, status) || ::flock(fileDescriptor.get(), LOCK_EX | LOCK_NB) != 0) { continue; }
			::unlinkat(root, entry->d_name, 0);
		}
	}
	bool publish(llvm::StringRef name, llvm::StringRef bytes) {
		std::string temporaryName; Descriptor descriptor(temporary(temporaryName));
		if (descriptor.get() < 0) { return false; }
		auto cleanup = llvm::make_scope_exit([&] { ::unlinkat(root, temporaryName.c_str(), 0); });
		return write(descriptor.get(), bytes) && ::fsync(descriptor.get()) == 0 &&
			::renameat(root, temporaryName.c_str(), root, name.str().c_str()) == 0 && ::fsync(root) == 0;
	}
	bool publishFragment(llvm::StringRef digest, llvm::StringRef bytes) {
		std::string name = "trace-" + digest.str(), existing;
		if (read(root, name, bytes.size(), existing) && existing == bytes) { return true; }
		std::string temporaryName; Descriptor descriptor(temporary(temporaryName));
		if (descriptor.get() < 0) { return false; }
		auto cleanup = llvm::make_scope_exit([&] { ::unlinkat(root, temporaryName.c_str(), 0); });
		if (!write(descriptor.get(), bytes) || ::fsync(descriptor.get()) != 0 || ::flock(root, LOCK_EX) != 0) { return false; }
		auto unlock = llvm::make_scope_exit([&] { ::flock(root, LOCK_UN); });
		// A concurrent publisher may have installed the same immutable fragment.
		// Preserve its inode, just as response-blob publication does.
		if (read(root, name, bytes.size(), existing) && existing == bytes) { return true; }
		return ::renameat(root, temporaryName.c_str(), root, name.c_str()) == 0;
	}
	bool storeTrace(llvm::json::Value& trace, uint64_t& expandedBytes) {
		const auto* document = trace.getAsObject();
		const auto* operations = document ? document->getArray("operations") : nullptr;
		if (!document || document->getBoolean("complete") != true || !operations) { return false; }
		llvm::json::Array fragments;
		std::string bytes = "[";
		unsigned rows = 0;
		expandedBytes = 0;
		auto flush = [&] {
			if (!rows) { return true; }
			bytes += "]";
			if (bytes.size() > receiptLimit - expandedBytes) { return false; }
			expandedBytes += bytes.size();
			std::string digest = NativeFileTrace::digest(bytes);
			if (!publishFragment(digest, bytes)) { return false; }
			fragments.push_back(digest); bytes = "["; rows = 0; return true;
		};
		for (const auto& row : *operations) {
			std::string encoded = llvm::formatv("{0}", row).str();
			if (encoded.size() + bytes.size() + 2 > receiptLimit) { return false; }
			if (rows++) { bytes += ","; }
			bytes += encoded;
			const std::string digest = NativeFileTrace::digest(encoded);
			// A boundary at six zero low bits of the first digest byte gives a
			// nominal 64-row interval, independent of earlier insertions/removals.
			bool boundary = digest[1] == '0' && (digest[0] == '0' || digest[0] == '4' || digest[0] == '8' || digest[0] == 'c');
			if ((boundary || rows == 256) && !flush()) { return false; }
		}
		// Make all fragment names durable before publishing a referring receipt.
		if (!flush() || ::fsync(root) != 0) { return false; }
		trace = llvm::json::Object{{"complete", true}, {"fragments", std::move(fragments)}};
		return true;
	}
	bool validateTrace(const llvm::json::Value& document, uint64_t limit) {
		const auto* trace = document.getAsObject();
		if (!trace || trace->getBoolean("complete") != true) { return false; }
		const auto* references = trace->getArray("fragments");
		if (!references || trace->get("operations")) { return false; }
		std::vector<const llvm::json::Array*> arrays;
		std::vector<std::unique_ptr<llvm::json::Value>> temporary;
		uint64_t expanded = 0;
		for (const auto& reference : *references) {
			auto digest = reference.getAsString();
			if (!digest || !hex(*digest)) { return false; }
			auto found = traceFragments.find(digest->str());
			if (found != traceFragments.end()) {
				if (found->second.bytes > limit - expanded) { return false; }
				expanded += found->second.bytes;
				arrays.push_back(found->second.rows.getAsArray()); continue;
			}
			std::string bytes;
			if (!read(root, "trace-" + digest->str(), limit - expanded, bytes) || NativeFileTrace::digest(bytes) != *digest) { return false; }
			expanded += bytes.size();
			auto parsed = llvm::json::parse(bytes);
			if (!parsed) { llvm::consumeError(parsed.takeError()); return false; }
			if (!parsed->getAsArray()) { return false; }
			// Retain verified immutable data only within this cache invocation.
			// This shares parsing, not the proof of current filesystem answers.
			if (bytes.size() <= receiptLimit - fragmentBytes) {
				fragmentBytes += bytes.size();
				auto inserted = traceFragments.emplace(digest->str(), TraceFragment{bytes.size(), std::move(*parsed)});
				arrays.push_back(inserted.first->second.rows.getAsArray());
			} else {
				temporary.push_back(std::make_unique<llvm::json::Value>(std::move(*parsed)));
				arrays.push_back(temporary.back()->getAsArray());
			}
		}
		return verifier.validate(arrays);
	}
	bool blob(int stage, const char* name, uint64_t limit, llvm::json::Object& result) {
		Descriptor input(::openat(stage, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
		struct stat before, after; if (!file(input.get(), limit, before)) { return false; }
		std::string temporaryName; Descriptor output(temporary(temporaryName));
		if (output.get() < 0) { return false; }
		auto cleanup = llvm::make_scope_exit([&] { ::unlinkat(root, temporaryName.c_str(), 0); });
		llvm::SHA256 hash; uint64_t count = 0; char buffer[65536];
		for (;;) {
			ssize_t size = ::read(input.get(), buffer, sizeof(buffer));
			if (size < 0 && errno == EINTR) { continue; }
			if (size < 0) { return false; } if (!size) { break; }
			count += static_cast<uint64_t>(size); if (count > limit) { return false; }
			llvm::StringRef bytes(buffer, static_cast<size_t>(size)); hash.update(bytes);
			if (!write(output.get(), bytes)) { return false; }
		}
		if (::fstat(input.get(), &after) != 0 || !same(before, after) || count != static_cast<uint64_t>(before.st_size)) { return false; }
		std::string digest = llvm::toHex(hash.final(), true);
		result = llvm::json::Object{{"sha256",digest},{"bytes",static_cast<int64_t>(count)}};
		// A content-addressed blob is immutable once valid. Replacing an equal
		// blob unlinks readers' open descriptors and fails their snapshot checks.
		// Serialize check/repair so concurrent publishers preserve the same inode.
		if (::flock(root, LOCK_EX) != 0) { return false; }
		auto unlock = llvm::make_scope_exit([&] { ::flock(root, LOCK_UN); });
		if (verifyBlob(result, limit)) { return true; }
		return ::fsync(output.get()) == 0 && ::renameat(root, temporaryName.c_str(), root, ("blob-" + digest).c_str()) == 0;
	}
	bool verifyBlob(const llvm::json::Object& value, uint64_t limit) {
		auto digest = value.getString("sha256"); auto expected = value.getInteger("bytes");
		if (!digest || !hex(*digest) || !expected || *expected < 0 || static_cast<uint64_t>(*expected) > limit) { return false; }
		Descriptor input(::openat(root, ("blob-" + digest->str()).c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
		struct stat before, after; if (!file(input.get(), limit, before) || before.st_size != *expected) { return false; }
		llvm::SHA256 hash; uint64_t count = 0; char buffer[65536];
		for (;;) {
			ssize_t size = ::read(input.get(), buffer, sizeof(buffer));
			if (size < 0 && errno == EINTR) { continue; }
			if (size < 0) { return false; } if (!size) { break; }
			count += static_cast<uint64_t>(size); if (count > limit) { return false; }
			hash.update(llvm::StringRef(buffer, static_cast<size_t>(size)));
		}
		return ::fstat(input.get(), &after) == 0 && same(before, after) && count == static_cast<uint64_t>(*expected) && llvm::toHex(hash.final(), true) == *digest;
	}
	static bool admitted(const llvm::json::Object& inputs) {
		if (inputs.getBoolean("eligible_runtime") != true || inputs.getBoolean("runtime_stable") != true) { return false; }
		const auto* reasons = inputs.getArray("exclusions");
		if (!reasons || inputs.getBoolean("eligible_inputs") != reasons->empty()) { return false; }
		// Successful worker diagnostics are retained as complete stderr blobs.
		for (const auto& reason : *reasons) { if (reason.getAsString() != "diagnostics") { return false; } }
		auto key = inputs.getString("identity_sha256"); const auto* identity = inputs.getArray("identity");
		return key && hex(*key) && identity && NativeFileTrace::digest(llvm::formatv("{0}", llvm::json::Value(llvm::json::Array(*identity))).str()) == *key;
	}
public:
	explicit NativeHeaderCache(llvm::StringRef path) : directory(path.str()) {
		if (!path.starts_with("/") || path.contains('\0')) { return; }
		int parent = ::open("/", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
		if (parent < 0) { return; }
		auto close = llvm::make_scope_exit([&] { if (parent >= 0) { ::close(parent); } });
		llvm::SmallVector<llvm::StringRef> components; path.split(components, '/', -1, false);
		if (components.empty()) { return; }
		for (auto component : components) {
			if (component == "." || component == "..") { return; }
			if (::mkdirat(parent, component.str().c_str(), 0700) != 0 && errno != EEXIST) { return; }
			int next = ::openat(parent, component.str().c_str(), O_RDONLY | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW);
			if (next < 0) { return; }
			::close(parent); parent = next; struct stat status;
			if (::fstat(parent, &status) != 0 || (status.st_uid != ::geteuid() && status.st_uid != 0) || (status.st_mode & 0022)) { return; }
		}
		struct stat status;
		if (::fstat(parent, &status) != 0 || status.st_uid != ::geteuid() || (status.st_mode & 0777) != 0700) { return; }
		root = parent; parent = -1;
		collectTemporaryFiles();
		WorkerStage::collect(root);
	}
	~NativeHeaderCache() { if (root >= 0) { ::close(root); } }
	NativeHeaderCache(const NativeHeaderCache&) = delete;
	NativeHeaderCache& operator=(const NativeHeaderCache&) = delete;
	bool valid() const { return root >= 0; }

	llvm::json::Object compilerContext(const std::vector<std::string>& drivers, llvm::StringRef compiler = "") {
		NativeCompilerContext context(drivers, compiler);
		if (!context.valid()) { return context.failure(); }
		if (!valid()) { return context.failure("capture-storage-unavailable"); }
		WorkerStage stage(root, directory);
		if (!stage.valid()) { return context.failure("capture-storage-unavailable"); }
		for (const auto* name : {"stdout", "stderr"}) {
			Descriptor file(::openat(stage.get(), name, O_WRONLY | O_CLOEXEC | O_NOFOLLOW | O_CREAT | O_EXCL, 0600));
			if (file.get() < 0) { return context.failure("capture-storage-unavailable"); }
		}
		if (!context.observe(stage.path())) { return context.failure("compiler-runtime-observation-failed"); }
		std::string output, errors;
		if (!read(stage.get(), "stdout", 65536, output) || !read(stage.get(), "stderr", 1024 * 1024, errors)) { return context.failure("invalid-runtime-capture"); }
		return context.finish(output, errors);
	}


	llvm::json::Object preprocess(const std::vector<std::string>& arguments, const llvm::json::Object& context, bool capture = true) {
		llvm::json::Object result{{"eligible", false}, {"cache_hit", false}};
		if (!valid()) { result["reason"] = "capture-storage-unavailable"; return result; }
		NativePreprocess operation(arguments, context);
		if (!operation.valid()) { result["reason"] = "unsupported-preprocessing-inputs"; return result; }
		result["identity_sha256"] = operation.contract().getString("identity_sha256")->str();
		llvm::json::Object response;
		if (lookup(operation.contract(), receiptLimit, response)) {
			result["eligible"] = true; result["cache_hit"] = true; result["response"] = std::move(response); return result;
		}
		if (!capture) { result["eligible"] = true; result["reason"] = "receipt-miss"; return result; }
		WorkerStage stage(root, directory);
		if (!stage.valid()) { result["reason"] = "capture-storage-unavailable"; return result; }
		for (const auto* name : {"stdout", "stderr", "preprocessed", "dependencies", "headers"}) {
			Descriptor file(::openat(stage.get(), name, O_WRONLY | O_CLOEXEC | O_NOFOLLOW | O_CREAT | O_EXCL, 0600));
			if (file.get() < 0) { result["reason"] = "capture-storage-unavailable"; return result; }
		}
		// Clang atomically replaces some outputs; their final files must retain
		// the private capture permissions even when the caller has a public umask.
		mode_t previousMask = ::umask(0077);
		auto restoreMask = llvm::make_scope_exit([&] { ::umask(previousMask); });
		llvm::json::Object contract, filesystem;
		llvm::json::Array buffers;
		if (!operation.run(stage.path(), contract, filesystem, buffers)) { result["reason"] = "preprocessing-not-reusable"; return result; }
		llvm::json::Object output{{"schema", "btrc.native-preprocessed.v1"}, {"buffers", std::move(buffers)}};
		for (const auto* name : {"preprocessed", "dependencies", "headers"}) {
			std::string bytes;
			if (!read(stage.get(), name, 256 * 1024 * 1024, bytes)) { result["reason"] = std::string("invalid-preprocessing-capture:") + name; return result; }
			output[name] = NativeFileTrace::digest(bytes);
		}
		std::map<std::string, std::string> documents{
			{"stdout", llvm::formatv("{0}", llvm::json::Value(std::move(output))).str()}, {"stderr", operation.errors()}};
		for (const auto& document : documents) {
			Descriptor file(::openat(stage.get(), document.first.c_str(), O_WRONLY | O_CLOEXEC | O_NOFOLLOW | O_TRUNC));
			if (file.get() < 0 || !write(file.get(), document.second)) { result["reason"] = "capture-storage-unavailable"; return result; }
		}
		// This capture owns its structured records. The publisher validates them
		// and returns descriptors only after committing their receipt and blobs.
		if (!contract.get("identity") || *contract.get("identity") != *operation.contract().get("identity") ||
			!store(stage.get(), receiptLimit, std::move(contract), std::move(filesystem), &response)) { result["reason"] = "receipt-not-published"; return result; }
		result["eligible"] = true; result["response"] = std::move(response); return result;
	}

	bool store(llvm::StringRef stageName, uint64_t outputLimit) {
		if (!valid() || !stageName.starts_with("stage-") || !hex(stageName.drop_front(6))) { return false; }
		Descriptor stage(::openat(root, stageName.str().c_str(), O_RDONLY | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW));
		return store(stage.get(), outputLimit);
	}
private:
	bool store(int stage, uint64_t outputLimit) {
		struct stat status;
		if (stage < 0 || ::fstat(stage, &status) != 0 || status.st_uid != ::geteuid() || (status.st_mode & 0777) != 0700) { return false; }
		std::string encodedInputs, encodedTrace;
		if (!read(stage, "inputs.json", receiptLimit, encodedInputs) || !read(stage, "filesystem.json", receiptLimit, encodedTrace)) { return false; }
		auto inputs = llvm::json::parse(encodedInputs), trace = llvm::json::parse(encodedTrace);
		if (!inputs || !trace) { if (!inputs) { llvm::consumeError(inputs.takeError()); } if (!trace) { llvm::consumeError(trace.takeError()); } return false; }
		return store(stage, outputLimit, std::move(*inputs), std::move(*trace));
	}
	bool store(int stage, uint64_t outputLimit, llvm::json::Value inputs, llvm::json::Value trace, llvm::json::Object* published = nullptr) {
		struct stat status;
		if (stage < 0 || ::fstat(stage, &status) != 0 || status.st_uid != ::geteuid() || (status.st_mode & 0777) != 0700) { return false; }
		const auto* contract = inputs.getAsObject();
		if (!contract || contract->getInteger("reader_exit") != 0 || !admitted(*contract) || !verifier.validate(trace)) { return false; }
		llvm::json::Object output, errors;
		if (!blob(stage, "stdout", outputLimit, output) || !blob(stage, "stderr", diagnosticLimit, errors)) { return false; }
		llvm::json::Object streams;
		if (published) { streams = responseDescriptors(output, errors); }
		std::string key = contract->getString("identity_sha256")->str();
		uint64_t expandedBytes = 0;
		if (!storeTrace(trace, expandedBytes)) { return false; }
		llvm::json::Object receipt{{"schema","btrc.native-header-cache.v2"},{"inputs",std::move(inputs)},
			{"filesystem",std::move(trace)},{"stdout",std::move(output)},{"stderr",std::move(errors)}};
		std::string bytes = llvm::formatv("{0}", llvm::json::Value(std::move(receipt))).str();
		if (bytes.size() + 65 > receiptLimit || expandedBytes > receiptLimit - bytes.size() - 65 || !publish(key + ".receipt", NativeFileTrace::digest(bytes) + "\n" + bytes)) { return false; }
		if (published) {
			if (!verifyBlob(*streams.getObject("stdout"), outputLimit) || !verifyBlob(*streams.getObject("stderr"), diagnosticLimit)) { return false; }
			*published = std::move(streams);
		}
		return true;
	}
	llvm::json::Object responseDescriptors(const llvm::json::Object& output, const llvm::json::Object& errors) const {
		llvm::json::Object response{{"stdout",llvm::json::Object(output)},{"stderr",llvm::json::Object(errors)}};
		for (const auto* stream : {"stdout", "stderr"}) {
			auto* metadata = response.getObject(stream);
			(*metadata)["path"] = directory + "/blob-" + metadata->getString("sha256")->str();
		}
		return response;
	}
public:
	std::optional<int> extract(const std::string& executable, const std::vector<std::string>& arguments, llvm::StringRef input, uint64_t outputLimit) {
		if (!valid()) { return std::nullopt; }
		WorkerStage stage(root, directory);
		if (!stage.valid()) { return std::nullopt; }
		for (const auto* name : {"stdin", "stdout", "stderr", "inputs.json", "filesystem.json"}) {
			Descriptor file(::openat(stage.get(), name, O_WRONLY | O_CLOEXEC | O_NOFOLLOW | O_CREAT | O_EXCL, 0600));
			if (file.get() < 0 || (llvm::StringRef(name) == "stdin" && !write(file.get(), input))) { return std::nullopt; }
		}
		const std::string& prefix = stage.path();
		std::vector<std::string> command{executable, "--input-report=" + prefix + "inputs.json", "--trace-files=" + prefix + "filesystem.json"};
		command.insert(command.end(), arguments.begin(), arguments.end());
		llvm::SmallVector<llvm::StringRef> argv; for (const auto& argument : command) { argv.push_back(argument); }
		std::string stdinPath = prefix + "stdin", stdoutPath = prefix + "stdout", stderrPath = prefix + "stderr";
		std::optional<llvm::StringRef> redirects[] = {stdinPath, stdoutPath, stderrPath};
		std::string failure;
		// The caller's process-group deadline still encloses this child. Each
		// selection keeps its original 60-second and 8 MiB capture allowance.
		unsigned seconds = static_cast<unsigned>((outputLimit + diagnosticLimit - 1) / diagnosticLimit) * 60;
		int status = llvm::sys::ExecuteAndWait(executable, argv, std::nullopt, redirects, seconds, 0, &failure);
		// Failure to launch (including unavailable capture paths) belongs to the
		// optional cache. Retry ordinary extraction before forwarding any bytes.
		// A started worker's crash/timeout is -2 and remains a terminal failure.
		if (status == -1) { return std::nullopt; }
		std::string output, errors;
		if (!read(stage.get(), "stdout", outputLimit, output) || !read(stage.get(), "stderr", diagnosticLimit, errors)) { return std::nullopt; }
		if (status == 0) { store(stage.get(), outputLimit); }
		llvm::outs() << output; llvm::errs() << errors;
		if (status < 0) { llvm::errs() << "error: native header reader child failed: " << failure << '\n'; return 1; }
		return status;
	}

	bool lookup(const llvm::json::Object& prepared, uint64_t outputLimit, llvm::json::Object& response) {
		if (!valid() || !admitted(prepared) || prepared.getBoolean("eligible_inputs") != true) { return false; }
		std::string key = prepared.getString("identity_sha256")->str(), bytes;
		if (!read(root, key + ".receipt", receiptLimit, bytes) || bytes.size() < 65 || bytes[64] != '\n') { return false; }
		llvm::StringRef payload(bytes.data() + 65, bytes.size() - 65);
		if (!hex(llvm::StringRef(bytes).take_front(64)) || NativeFileTrace::digest(payload) != llvm::StringRef(bytes).take_front(64)) { return false; }
		auto receipt = llvm::json::parse(payload);
		if (!receipt) { llvm::consumeError(receipt.takeError()); return false; }
		const auto* value = receipt->getAsObject();
		if (!value) { return false; }
		auto schema = value->getString("schema");
		if (schema != "btrc.native-header-cache.v1" && schema != "btrc.native-header-cache.v2") { return false; }
		const auto* inputs = value->getObject("inputs"); const auto* trace = value->get("filesystem");
		const auto* output = value->getObject("stdout"); const auto* errors = value->getObject("stderr");
		if (!inputs || inputs->getInteger("reader_exit") != 0 || !admitted(*inputs) || !inputs->get("identity") || *inputs->get("identity") != *prepared.get("identity") ||
			!trace || !output || !errors || !verifyBlob(*output, outputLimit) || !verifyBlob(*errors, diagnosticLimit) ||
			!(schema == "btrc.native-header-cache.v1" ? verifier.validate(*trace) : validateTrace(*trace, receiptLimit - bytes.size()))) { return false; }
		response = responseDescriptors(*output, *errors);
		return true;
	}
};

#else
class NativeHeaderCache {
public:
	explicit NativeHeaderCache(llvm::StringRef) {}
	llvm::json::Object compilerContext(const std::vector<std::string>& drivers, llvm::StringRef compiler = "") { return NativeCompilerContext(drivers, compiler).failure("unsupported-compiler-provider"); }
	llvm::json::Object preprocess(const std::vector<std::string>&, const llvm::json::Object&, bool = true) { return llvm::json::Object{{"eligible", false}, {"cache_hit", false}, {"reason", "unsupported-compiler-provider"}}; }
	bool store(llvm::StringRef, uint64_t) { return false; }
	std::optional<int> extract(const std::string&, const std::vector<std::string>&, llvm::StringRef, uint64_t) { return std::nullopt; }
	bool valid() const { return false; }
	bool lookup(const llvm::json::Object&, uint64_t, llvm::json::Object&) { return false; }
};
#endif

// Session preparation stops at the same effective CompilerInvocation used by
// fresh extraction. Cache lookup follows preparation and validates the recorded
// filesystem answers before returning response descriptors.
class NativeHeaderSession {
	llvm::json::Value runtime = llvm::json::Value(NativeRuntimeInputs::capture());
	struct DependencyFlags { std::vector<std::string> flags; std::string diagnostics; };
	std::map<std::pair<std::string, std::vector<std::string>>, DependencyFlags> dependencyFlags;
	int64_t dependencyRuns = 0;

	bool resolve(const std::vector<std::string>& packages, DependencyFlags& result) {
		auto cwd = llvm::vfs::getRealFileSystem()->getCurrentWorkingDirectory();
		if (!cwd) { return false; }
		auto key = std::make_pair(*cwd, packages);
		auto found = dependencyFlags.find(key);
		if (found != dependencyFlags.end()) { result = found->second; return true; }
		NativeHeaderDependencies dependencies;
		if (!packages.empty()) { ++dependencyRuns; }
		if (!dependencies.resolve(packages, result.flags, true)) { return false; }
		result.diagnostics = dependencies.diagnostics();
		dependencyFlags.emplace(std::move(key), result);
		return true;
	}

	llvm::json::Object prepare(const llvm::json::Object& group) {
		auto id = group.getString("id");
		llvm::json::Object result{{"id", id ? llvm::json::Value(id->str()) : llvm::json::Value(nullptr)}, {"prepared", false}};
		const auto* encoded = group.getArray("arguments");
		if (!encoded) { return result; }
		std::vector<std::string> arguments, symbols, paths, values, packages, flags;
		std::string source;
		bool compilerFlags = false, batch = false;
		for (const auto& value : *encoded) {
			auto text = value.getAsString();
			if (!text || text->contains('\0')) { return result; }
			arguments.push_back(text->str());
			if (compilerFlags) { flags.push_back(text->str()); continue; }
			if (*text == "--") { compilerFlags = true; continue; }
			if (*text == "--batch=-") { if (batch) { return result; } batch = true; }
			else if (text->starts_with("--symbol=")) { symbols.push_back(text->drop_front(9).str()); }
			else if (text->starts_with("--record-path=")) { paths.push_back(text->drop_front(14).str()); }
			else if (text->starts_with("--record-value=")) { values.push_back(text->drop_front(15).str()); }
			else if (text->starts_with("--pkg-config=")) { packages.push_back(text->drop_front(13).str()); }
			else if (text->empty() || text->starts_with("-") || !source.empty()) { return result; }
			else { source = text->str(); }
		}
		if (!compilerFlags || source.empty()) { return result; }
		NativeHeaderRequests requests;
		if (batch) {
			auto input = group.getString("input");
			if (!symbols.empty() || !paths.empty() || !values.empty() || !input || !requests.loadText(*input)) { return result; }
		} else {
			if (symbols.empty() || (group.get("input") && *group.get("input") != llvm::json::Value(nullptr))) { return result; }
			for (const auto* selections : {&symbols, &paths, &values}) {
				for (const auto& selection : *selections) { if (selection.empty()) { return result; } }
			}
			requests.add("", symbols, paths, values);
		}
		DependencyFlags dependencies;
		if (!resolve(packages, dependencies)) { return result; }
		NativeHeaderInputs inputs(&runtime);
		inputs.request(arguments, dependencies.diagnostics);
		NativeHeaderActionFactory factory(requests, &inputs, true);
		clang::tooling::FixedCompilationDatabase database(".", flags);
		clang::tooling::ClangTool tool(database, {source});
		tool.appendArgumentsAdjuster(clang::tooling::getInsertArgumentAdjuster(dependencies.flags, clang::tooling::ArgumentInsertPosition::BEGIN));
		if (tool.run(&factory) != 0) { return result; }
		result["prepared"] = true;
		result["inputs"] = inputs.report(requests.selections(), &runtime);
		return result;
	}
public:
	static std::optional<llvm::json::Value> load(llvm::StringRef path) {
		// Session control stays bounded; unsupported/oversized sessions use the
		// existing per-group extraction path rather than shrinking that API.
		std::ifstream file;
		if (path != "-") { file.open(path.str(), std::ios::binary); if (!file) { return std::nullopt; } }
		std::istream& input = path == "-" ? std::cin : file;
		std::string bytes; char buffer[8192];
		while (input.read(buffer, sizeof(buffer)) || input.gcount()) {
			if (bytes.size() + static_cast<size_t>(input.gcount()) > 8 * 1024 * 1024) { return std::nullopt; }
			bytes.append(buffer, static_cast<size_t>(input.gcount()));
		}
		if (!input.eof()) { return std::nullopt; }
		auto parsed = llvm::json::parse(bytes);
		if (!parsed) { llvm::consumeError(parsed.takeError()); return std::nullopt; }
		return std::move(*parsed);
	}

	int run(llvm::StringRef path, bool store = false, llvm::StringRef launcher = "") {
		auto parsed = load(path); if (!parsed) { return 1; }
		const auto* document = parsed->getAsObject();
		if (!document || (document->size() < 2 || document->size() > 4) || document->getString("schema") != "btrc.native-session-requests.v1") { return 1; }
		for (const auto& member : *document) {
			if (member.first != "schema" && member.first != "groups" && member.first != "cache_directory" && member.first != "compact") { return 1; }
		}
		if (document->get("compact") && !document->getBoolean("compact")) { return 1; }
		bool compact = document->getBoolean("compact").value_or(false);
		std::unique_ptr<NativeHeaderCache> cache;
		if (auto path = document->getString("cache_directory")) { cache = std::make_unique<NativeHeaderCache>(*path); }
		if (store && !cache) { return 1; }
		const auto* groups = document->getArray("groups");
		if (!groups || groups->empty()) { return 1; }
		std::set<std::string> identities;
		for (const auto& value : *groups) {
			const auto* group = value.getAsObject(); if (!group) { return 1; }
			auto id = group->getString("id");
			if (!id || id->empty() || id->contains('\0') || !identities.insert(id->str()).second) { return 1; }
			for (const auto& member : *group) {
				if (member.first != "id" && member.first != "arguments" && member.first != "input" && member.first != "stage" && member.first != "output_limit") { return 1; }
			}
		}
		llvm::json::Array results;
		for (const auto& value : *groups) {
			const auto& group = *value.getAsObject();
			auto limit = group.getInteger("output_limit");
			bool bounded = limit && *limit > 0 && *limit <= INT32_MAX - 8 * 1024 * 1024;
			if (store) {
				auto stage = group.getString("stage");
				bool stored = bounded && stage && cache->store(*stage, static_cast<uint64_t>(*limit));
				results.push_back(llvm::json::Object{{"id",group.getString("id")->str()},{"stored",stored}});
			} else {
				auto prepared = prepare(group); llvm::json::Object response;
				bool hit = cache && bounded && prepared.getBoolean("prepared") == true &&
					cache->lookup(*prepared.getObject("inputs"), static_cast<uint64_t>(*limit), response);
				prepared["cache_hit"] = hit;
				prepared["cache_ready"] = cache && cache->valid();
				if (hit) { prepared["response"] = std::move(response); }
				const auto* inputs = prepared.getObject("inputs");
				prepared["cache_eligible"] = prepared.getBoolean("prepared") == true && cache && cache->valid() && inputs &&
					inputs->getBoolean("eligible_inputs") == true && inputs->getBoolean("eligible_runtime") == true;
				if (compact) { prepared.erase("inputs"); }

				results.push_back(std::move(prepared));
			}
		}
		llvm::json::Value after(NativeRuntimeInputs::capture());
		if (runtime != after) {
			for (auto& value : results) { (*value.getAsObject())["prepared"] = false; (*value.getAsObject())["cache_hit"] = false; value.getAsObject()->erase("response"); }
		}
		auto response = llvm::formatv("{0}\n", llvm::json::Value(llvm::json::Object{
			{"schema", "btrc.native-session-prepared.v1"}, {"launcher", launcher.str()}, {"eligible_launcher", NativeRuntimeInputs::immutableStorePath(launcher)}, {"dependency_queries",dependencyRuns}, {"runtime_stable",runtime == after}, {"groups",std::move(results)}})).str();
		if (response.size() > 8 * 1024 * 1024) { return 1; }
		llvm::outs() << response;
		return 0;
	}
};

class NativePreprocessSession {
public:
	static int run(llvm::StringRef path, llvm::StringRef launcher) {
		auto parsed = NativeHeaderSession::load(path);
		const auto* request = parsed ? parsed->getAsObject() : nullptr;
		if (!request || request->size() < 4 || request->size() > 5 || request->getString("schema") != "btrc.native-preprocess.v1") { return 1; }
		for (const auto& field : *request) {
			if (field.first != "schema" && field.first != "cache_directory" && field.first != "drivers" && field.first != "units" && field.first != "capture") { return 1; }
		}
		if (request->get("capture") && !request->getBoolean("capture")) { return 1; }
		bool capture = request->getBoolean("capture").value_or(true);
		auto directory = request->getString("cache_directory");
		const auto* selected = request->getArray("drivers"); const auto* units = request->getArray("units");
		if (!directory || directory->contains('\0') || !selected || selected->empty() || selected->size() > 16 || !units || units->empty() || units->size() > 1024) { return 1; }
		std::vector<std::string> drivers;
		for (const auto& value : *selected) {
			auto text = value.getAsString(); if (!text || text->empty() || text->contains('\0')) { return 1; }
			drivers.push_back(text->str());
		}
		std::set<std::string> ids;
		std::vector<std::pair<std::string, std::vector<std::string>>> commands;
		for (const auto& value : *units) {
			const auto* unit = value.getAsObject(); if (!unit || unit->size() != 2) { return 1; }
			auto id = unit->getString("id"); const auto* encoded = unit->getArray("cc1");
			if (!id || id->empty() || id->contains('\0') || !ids.insert(id->str()).second || !encoded || encoded->empty()) { return 1; }
			std::vector<std::string> arguments;
			for (const auto& argument : *encoded) {
				auto text = argument.getAsString(); if (!text || text->contains('\0')) { return 1; } arguments.push_back(text->str());
			}
			commands.emplace_back(id->str(), std::move(arguments));
		}
		NativeHeaderCache cache(*directory);
		std::map<std::string, llvm::json::Object> contexts;
		llvm::json::Array results, bindings;
		if (NativeRuntimeInputs::immutableStorePath(launcher)) {
			for (const auto& command : commands) {
				const auto& compiler = command.second.front();
				auto found = contexts.find(compiler);
				if (found == contexts.end()) { found = contexts.emplace(compiler, cache.compilerContext(drivers, compiler)).first; }
				auto result = cache.preprocess(command.second, found->second, capture); result["id"] = command.first; results.push_back(std::move(result));
			}
		}
		for (auto& entry : contexts) { bindings.push_back(std::move(entry.second)); }
		auto response = llvm::formatv("{0}\n", llvm::json::Value(llvm::json::Object{{"schema", "btrc.native-preprocess.v1"},
			{"launcher", launcher.str()}, {"eligible_launcher", NativeRuntimeInputs::immutableStorePath(launcher)},
			{"contexts", std::move(bindings)}, {"units", std::move(results)}})).str();
		if (response.size() > 8 * 1024 * 1024) { return 1; }
		llvm::outs() << response;
		return 0;
	}
};

class NativeHeaderCommand {
	static int compilerContext(llvm::StringRef path, llvm::StringRef launcher) {
		auto parsed = NativeHeaderSession::load(path);
		const auto* request = parsed ? parsed->getAsObject() : nullptr;
		if (!request || request->size() != 3 || request->getString("schema") != "btrc.native-compiler-context.v1") { return 1; }
		auto directory = request->getString("cache_directory"); const auto* selected = request->getArray("drivers");
		if (!directory || directory->contains('\0') || !selected || selected->empty() || selected->size() > 16) { return 1; }
		std::vector<std::string> drivers;
		for (const auto& value : *selected) {
			auto driver = value.getAsString(); if (!driver || driver->empty() || driver->contains('\0')) { return 1; }
			drivers.push_back(driver->str());
		}
		auto result = NativeHeaderCache(*directory).compilerContext(drivers);
		result["launcher"] = launcher.str(); result["eligible_launcher"] = NativeRuntimeInputs::immutableStorePath(launcher);
		llvm::outs() << llvm::formatv("{0}\n", llvm::json::Value(std::move(result)));
		return 0;
	}

	static int extract(int argc, const char** argv, const std::string* batchInput = nullptr) {
	std::vector<std::string> requestArguments;
	bool readerOptions = true;
	for (int i = 1; i < argc; ++i) {
		llvm::StringRef argument(argv[i]);
		if (argument == "--") { readerOptions = false; }
		if (!readerOptions || (!argument.starts_with("--input-report=") && !argument.starts_with("--trace-files="))) {
			requestArguments.push_back(argument.str());
		}
	}
	llvm::cl::OptionCategory category("BTRC native header reader");
	llvm::cl::opt<std::string> inputReport("input-report", llvm::cl::desc("Write the effective native input contract for cache publication"), llvm::cl::cat(category));
	llvm::cl::opt<std::string> traceFiles("trace-files", llvm::cl::desc("Write the filesystem witness for cache publication"), llvm::cl::cat(category));
	llvm::cl::list<std::string> symbols("symbol", llvm::cl::desc("Exact qualified declaration to read"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	llvm::cl::opt<std::string> batch("batch", llvm::cl::desc("Independent selections for this translation unit (btrc.native-requests.v1 JSON; - reads stdin)"), llvm::cl::cat(category));
	llvm::cl::list<std::string> recordPaths("record-path", llvm::cl::desc("Selected owner and checked dotted SDK field path"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	llvm::cl::list<std::string> recordValues("record-value", llvm::cl::desc("Selected C++ public scalar record copied by value"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	llvm::cl::list<std::string> packages("pkg-config", llvm::cl::desc("Selected native dependency supplying compile flags"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	auto options = clang::tooling::CommonOptionsParser::create(argc, argv, category, llvm::cl::OneOrMore);
	if (!options) { llvm::errs() << options.takeError(); return 1; }
	if (options->getSourcePathList().size() != 1) { llvm::errs() << "error: expected exactly one native translation unit\n"; return 1; }
	NativeHeaderRequests requests;
	if (batch.getNumOccurrences()) {
		if (!symbols.empty() || !recordPaths.empty() || !recordValues.empty()) { llvm::errs() << "error: batch cannot be combined with standalone selections\n"; return 1; }
		if (!(batch == "-" && batchInput ? requests.loadText(*batchInput) : requests.load(batch))) { return 1; }
	} else {
		if (symbols.empty()) { llvm::errs() << "error: expected at least one --symbol or a --batch\n"; return 1; }
		requests.add("", std::vector<std::string>(symbols.begin(), symbols.end()), std::vector<std::string>(recordPaths.begin(), recordPaths.end()), std::vector<std::string>(recordValues.begin(), recordValues.end()));
	}
	std::vector<std::string> flags;
	NativeHeaderDependencies dependencies;
	bool captureInputs = !inputReport.empty();
	if (!dependencies.resolve(std::vector<std::string>(packages.begin(), packages.end()), flags, captureInputs)) { return 1; }
	std::unique_ptr<NativeHeaderInputs> inputs;
	if (captureInputs) {
		inputs = std::make_unique<NativeHeaderInputs>();
		inputs->request(requestArguments, dependencies.diagnostics());
	}
	NativeHeaderActionFactory factory(requests, inputs.get());
	NativeFileTrace trace;
	llvm::IntrusiveRefCntPtr<llvm::vfs::FileSystem> fs = llvm::vfs::getRealFileSystem();
	if (!traceFiles.empty()) { fs = llvm::makeIntrusiveRefCnt<NativeTracedFileSystem>(fs, trace); }
	clang::tooling::ClangTool tool(options->getCompilations(), options->getSourcePathList(), std::make_shared<clang::PCHContainerOperations>(), fs);
	tool.appendArgumentsAdjuster(clang::tooling::getInsertArgumentAdjuster(flags, clang::tooling::ArgumentInsertPosition::BEGIN));
	int result = tool.run(&factory);
	if (result == 0) { result = requests.publish(batch.getNumOccurrences() != 0) ? 0 : 1; }
	if (inputs) {
		inputs->completed(result);
		if (!inputs->write(inputReport, requests.selections())) { return 1; }
	}
	if (!traceFiles.empty() && !trace.write(traceFiles)) { return 1; }
	return result;
	}

	static int cached(llvm::StringRef path, const char* executableName) {
		auto parsed = NativeHeaderSession::load(path);
		const auto* request = parsed ? parsed->getAsObject() : nullptr;
		if (!request || request->size() != 5 || request->getString("schema") != "btrc.native-read.v1") { return 1; }
		auto directory = request->getString("cache_directory");
		auto limit = request->getInteger("output_limit");
		const auto* encoded = request->getArray("arguments");
		const auto* payload = request->get("input");
		if (!directory || !limit || *limit <= 0 || *limit > INT32_MAX - 8 * 1024 * 1024 || !encoded || encoded->empty() || !payload || (!payload->getAsString() && *payload != llvm::json::Value(nullptr))) { return 1; }
		std::vector<std::string> arguments;
		bool compilerFlags = false;
		for (const auto& value : *encoded) {
			auto argument = value.getAsString(); if (!argument || argument->contains('\0')) { return 1; }
			if (*argument == "--") { compilerFlags = true; }
			if (!compilerFlags && (argument->starts_with("--input-report") || argument->starts_with("--trace-files") || argument->contains("native-session") || argument->starts_with("--cached-native-read"))) { return 1; }
			arguments.push_back(argument->str());
		}
		if (!compilerFlags) { return 1; }
		std::string input = payload->getAsString().value_or("").str();
		static int executableAnchor;
		std::string executable = llvm::sys::fs::getMainExecutable(executableName, &executableAnchor);
		if (!executable.empty()) {
			if (auto status = NativeHeaderCache(*directory).extract(executable, arguments, input, static_cast<uint64_t>(*limit))) { return *status; }
		}
		// Optional storage cannot prevent a valid extraction. No observation
		// options have entered this argv, and batch stdin remains owned here.
		std::vector<const char*> argv{executableName};
		for (const auto& argument : arguments) { argv.push_back(argument.c_str()); }
		int argc = static_cast<int>(argv.size());
		return extract(argc, argv.data(), &input);
	}
public:
	static int run(int argc, const char** argv) {
		if (argc == 2) {
			llvm::StringRef option(argv[1]);
			if (option.starts_with("--native-preprocess=")) { return NativePreprocessSession::run(option.drop_front(20), argv[0]); }
			if (option.starts_with("--native-compiler-context=")) { return compilerContext(option.drop_front(26), argv[0]); }
			if (option.starts_with("--store-native-session=")) { return NativeHeaderSession().run(option.drop_front(23), true, argv[0]); }
			if (option.starts_with("--prepare-native-session=")) { return NativeHeaderSession().run(option.drop_front(25), false, argv[0]); }
			if (option.starts_with("--cached-native-read=")) { return cached(option.drop_front(21), argv[0]); }
		}
		return extract(argc, argv);
	}
};

int main(int argc, const char** argv) { return NativeHeaderCommand::run(argc, argv); }
