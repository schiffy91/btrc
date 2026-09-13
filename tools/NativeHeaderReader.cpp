#include <clang/AST/ASTConsumer.h>
#include <clang/AST/ASTContext.h>
#include <clang/AST/Attr.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/AST/RecordLayout.h>
#include <clang/Basic/TargetInfo.h>
#include <clang/Basic/Version.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Index/USRGeneration.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/ArgumentsAdjusters.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/Support/CommandLine.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/FileUtilities.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/Program.h>
#include <llvm/Support/StringSaver.h>
#include <llvm/Support/raw_ostream.h>

#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

// Build-time semantic reader for C ABI declarations and Objective-C methods.
// Unsupported declarations fail rather than losing type/lifetime information.
// Both BTRC frontends consume the same checked semantic model.
class NativeHeaderReader : public clang::RecursiveASTVisitor<NativeHeaderReader> {
	clang::ASTContext* context = nullptr;
	std::set<std::string> requested;
	std::vector<std::string> recordPaths;
	std::set<std::string> recordValues;
	std::map<std::string, const clang::NamedDecl*> declarations;
	std::map<std::string, const clang::ObjCInterfaceDecl*> interfaces;
	std::map<std::string, const clang::ObjCProtocolDecl*> protocols;
	std::map<std::string, const clang::CXXRecordDecl*> cppClasses;
	std::map<std::string, llvm::json::Object> selectedInterfaces;
	std::map<std::string, clang::Selector> selectors;
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

	std::string declarationName(const clang::NamedDecl* declaration) const {
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

	std::string objectiveCReceiver(const std::string& name) const {
		if (name.size() < 5 || (name[0] != '+' && name[0] != '-') || name[1] != '[' || name.back() != ']') { return ""; }
		auto separator = name.find(' ', 2);
		return separator == std::string::npos ? "" : name.substr(2, separator - 2);
	}

	const clang::ObjCMethodDecl* lookupObjectiveCMethod(const std::string& name) const {
		auto receiver = objectiveCReceiver(name);
		if (receiver.empty()) { return nullptr; }
		auto selector = selectors.find(name.substr(receiver.size() + 3, name.size() - receiver.size() - 4));
		if (selector == selectors.end()) { return nullptr; }
		auto interface = interfaces.find(receiver);
		if (interface == interfaces.end()) {
			auto protocol = protocols.find(receiver);
			if (protocol == protocols.end()) { return nullptr; }
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
		auto receiver = cppClasses.find(name.substr(0, separator));
		std::string method = name.substr(separator + 2);
		bool zeroParameters = method.size() > 2 && method.compare(method.size() - 2, 2, "()") == 0;
		if (zeroParameters) { method.resize(method.size() - 2); }
		return receiver == cppClasses.end() ? nullptr : lookupCppMethod(receiver->second, method, zeroParameters);
	}

	void requestCppRecordValue(const std::string& name) {
		auto found = cppClasses.find(name);
		const auto* record = found == cppClasses.end() ? nullptr : found->second->getDefinition();
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
		errors.push_back("Unsupported Objective-C method family: " + declarationName(method));
		return "unsupported";
	}

	llvm::json::Object declaration(const clang::NamedDecl* value) {
		auto location = context->getSourceManager().getPresumedLoc(value->getLocation());
		llvm::json::Object result{{"name", declarationName(value)}};
		if (location.isValid()) {
			result["source"] = location.getFilename();
			result["line"] = static_cast<int64_t>(location.getLine());
			result["column"] = static_cast<int64_t>(location.getColumn());
		}
		if (const auto* method = llvm::dyn_cast<clang::ObjCMethodDecl>(value)) {
			const auto* owner = method->getClassInterface();
			const auto* protocol = llvm::dyn_cast<clang::ObjCProtocolDecl>(method->getDeclContext());
			if (!owner && !protocol) { errors.push_back("Unsupported Objective-C method owner: " + declarationName(value)); return result; }
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
				errors.push_back("C++ methods require unambiguous public non-template instance methods: " + declarationName(method));
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
				errors.push_back("C++ resources require complete non-template SDK classes: " + declarationName(record));
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
		auto owner = declarations.find(path.substr(0, separator));
		const auto* declaration = owner == declarations.end() ? nullptr : owner->second;
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
		if (!requested.count(name)) { return true; }
		auto found = declarations.find(name);
		if (found != declarations.end() && found->second->getCanonicalDecl() != value->getCanonicalDecl()) {
			// C tags occupy a different namespace: `typedef struct Foo Foo` is
			// one usable ordinary name, not an ambiguous declaration request.
			if (!context->getLangOpts().CPlusPlus && llvm::isa<clang::TagDecl>(value) != llvm::isa<clang::TagDecl>(found->second)) {
				if (llvm::isa<clang::TagDecl>(found->second)) { declarations[name] = value; }
				return true;
			}
			errors.push_back("Ambiguous native declaration: " + name);
		} else {
			declarations[name] = value;
		}
		return true;
	}

	void read(clang::ASTContext& value) {
		if (value.getDiagnostics().hasErrorOccurred()) { return; }
		context = &value;
		target = value.getTargetInfo().getTriple().str();
		bigEndian = value.getTargetInfo().isBigEndian();
		characterBits = value.getTargetInfo().getCharWidth();
		TraverseDecl(value.getTranslationUnitDecl());
		for (const auto& name : recordValues) { requestCppRecordValue(name); }
		for (const auto& name : requested) {
			auto found = declarations.find(name);
			const clang::NamedDecl* selected = found == declarations.end() ? lookupObjectiveCMethod(name) : found->second;
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
					auto receiver = interfaces.find(objectiveCReceiver(name));
					if (receiver != interfaces.end()) { requestInterface(receiver->second); }
					if (const auto* owner = llvm::cast<clang::ObjCMethodDecl>(selected)->getClassInterface()) { requestInterface(owner); }
				}
				exports.push_back(std::move(exported));
			}
		}
		for (const auto& path : recordPaths) { requestRecordPath(path); }
		if (errors.empty() && !value.getDiagnostics().hasErrorOccurred()) { readRecords(); }
		pendingRecords.clear();
		declarations.clear();
		interfaces.clear();
		protocols.clear();
		cppClasses.clear();
		selectors.clear();
		context = nullptr;
	}

	bool publish() {
		if (!errors.empty()) {
			for (const auto& error : errors) { llvm::errs() << "error: " << error << '\n'; }
			return false;
		}
		llvm::json::Array layouts;
		for (auto& record : records) { layouts.push_back(std::move(record.second)); }
		llvm::json::Array interfaceDeclarations;
		for (auto& interface : selectedInterfaces) { interfaceDeclarations.push_back(std::move(interface.second)); }
		llvm::json::Object document{{"schema", "btrc.native-declarations.experimental"}, {"target", target}, {"clang", clang::getClangFullVersion()}, {"big_endian", bigEndian}, {"character_bits", static_cast<int64_t>(characterBits)}, {"declarations", std::move(exports)}, {"records", std::move(layouts)}, {"interfaces", std::move(interfaceDeclarations)}};
		llvm::outs() << llvm::formatv("{0:2}\n", llvm::json::Value(std::move(document)));
		return true;
	}
};

class NativeHeaderConsumer : public clang::ASTConsumer {
	NativeHeaderReader& reader;

public:
	explicit NativeHeaderConsumer(NativeHeaderReader& value) : reader(value) {}
	void HandleTranslationUnit(clang::ASTContext& context) override { reader.read(context); }
};

class NativeHeaderAction : public clang::ASTFrontendAction {
	NativeHeaderReader& reader;

public:
	explicit NativeHeaderAction(NativeHeaderReader& value) : reader(value) {}
	std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance&, llvm::StringRef) override { return std::make_unique<NativeHeaderConsumer>(reader); }
};

class NativeHeaderActionFactory : public clang::tooling::FrontendActionFactory {
	NativeHeaderReader& reader;

public:
	explicit NativeHeaderActionFactory(NativeHeaderReader& value) : reader(value) {}
	std::unique_ptr<clang::FrontendAction> create() override { return std::make_unique<NativeHeaderAction>(reader); }
};

// Resolve dependency-owned flags in the shared host tool, so both frontends
// inspect the same headers that the native build plan compiles against.
class NativeHeaderDependencies {
public:
	bool resolve(const std::vector<std::string>& packages, std::vector<std::string>& flags) {
		if (packages.empty()) { return true; }
		auto executable = llvm::sys::findProgramByName("pkg-config");
		if (!executable) { llvm::errs() << "error: native imports require pkg-config: " << executable.getError().message() << '\n'; return false; }
		llvm::SmallString<128> output;
		if (auto error = llvm::sys::fs::createTemporaryFile("btrc-native-cflags", "txt", output)) {
			llvm::errs() << "error: cannot capture pkg-config flags: " << error.message() << '\n';
			return false;
		}
		llvm::FileRemover cleanup(output);
		llvm::SmallVector<llvm::StringRef> arguments{*executable, "--cflags", "--"};
		for (const auto& package : packages) { arguments.push_back(package); }
		std::optional<llvm::StringRef> redirects[] = {llvm::StringRef(""), output.str(), std::nullopt};
		std::string error;
		if (llvm::sys::ExecuteAndWait(*executable, arguments, std::nullopt, redirects, 30, 0, &error) != 0) {
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

int main(int argc, const char** argv) {
	llvm::cl::OptionCategory category("BTRC native header reader");
	llvm::cl::list<std::string> symbols("symbol", llvm::cl::desc("Exact qualified declaration to read"), llvm::cl::OneOrMore, llvm::cl::cat(category));
	llvm::cl::list<std::string> recordPaths("record-path", llvm::cl::desc("Selected owner and checked dotted SDK field path"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	llvm::cl::list<std::string> recordValues("record-value", llvm::cl::desc("Selected C++ public scalar record copied by value"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	llvm::cl::list<std::string> packages("pkg-config", llvm::cl::desc("Selected native dependency supplying compile flags"), llvm::cl::ZeroOrMore, llvm::cl::cat(category));
	auto options = clang::tooling::CommonOptionsParser::create(argc, argv, category, llvm::cl::OneOrMore);
	if (!options) { llvm::errs() << options.takeError(); return 1; }
	if (options->getSourcePathList().size() != 1) { llvm::errs() << "error: expected exactly one native translation unit\n"; return 1; }
	std::vector<std::string> flags;
	if (!NativeHeaderDependencies().resolve(std::vector<std::string>(packages.begin(), packages.end()), flags)) { return 1; }
	NativeHeaderReader reader(std::vector<std::string>(symbols.begin(), symbols.end()), std::vector<std::string>(recordPaths.begin(), recordPaths.end()), std::vector<std::string>(recordValues.begin(), recordValues.end()));
	NativeHeaderActionFactory factory(reader);
	clang::tooling::ClangTool tool(options->getCompilations(), options->getSourcePathList());
	tool.appendArgumentsAdjuster(clang::tooling::getInsertArgumentAdjuster(flags, clang::tooling::ArgumentInsertPosition::BEGIN));
	if (tool.run(&factory) != 0) { return 1; }
	return reader.publish() ? 0 : 1;
}
