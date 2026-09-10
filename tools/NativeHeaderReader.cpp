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
#include <clang/Tooling/Tooling.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/Support/CommandLine.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/raw_ostream.h>

#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

// Build-time semantic reader. This slice exports C scalar, record and handle
// declarations; unsupported selected declarations fail instead of losing type
// information. It is not yet connected to either BTRC frontend.
class NativeHeaderReader : public clang::RecursiveASTVisitor<NativeHeaderReader> {
	clang::ASTContext* context = nullptr;
	std::set<std::string> requested;
	std::map<std::string, const clang::NamedDecl*> declarations;
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

	std::string requestRecord(const clang::RecordDecl* record, bool opaque) {
		auto identity = declarationIdentity(record);
		if (!opaque) {
			if (llvm::isa<clang::CXXRecordDecl>(record)) { errors.push_back("C++ record adapters are not implemented: " + record->getQualifiedNameAsString()); }
			else if (const auto* definition = record->getDefinition()) { pendingRecords.emplace(identity, definition); }
			else { errors.push_back("Incomplete by-value native record: " + record->getQualifiedNameAsString()); }
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
		if (const auto* alias = llvm::dyn_cast<clang::TypedefType>(node)) {
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
			result["complete"] = record->getDecl()->getDefinition() != nullptr;
			result["opaque"] = indirect;
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
			result["name"] = enumeration->getDecl()->getQualifiedNameAsString();
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

	std::string returnedOwnership(const clang::FunctionDecl* function) const {
		if (function->hasAttr<clang::CFReturnsRetainedAttr>()) { return "cf_retained"; }
		if (function->hasAttr<clang::CFReturnsNotRetainedAttr>()) { return "cf_not_retained"; }
		if (function->hasAttr<clang::NSReturnsRetainedAttr>()) { return "ns_retained"; }
		if (function->hasAttr<clang::NSReturnsNotRetainedAttr>()) { return "ns_not_retained"; }
		if (function->hasAttr<clang::NSReturnsAutoreleasedAttr>()) { return "ns_autoreleased"; }
		return "unspecified";
	}

	llvm::json::Object declaration(const clang::NamedDecl* value) {
		auto location = context->getSourceManager().getPresumedLoc(value->getLocation());
		llvm::json::Object result{{"name", value->getQualifiedNameAsString()}};
		if (location.isValid()) {
			result["source"] = location.getFilename();
			result["line"] = static_cast<int64_t>(location.getLine());
			result["column"] = static_cast<int64_t>(location.getColumn());
		}
		if (const auto* function = llvm::dyn_cast<clang::FunctionDecl>(value)) {
			if (function->hasAttr<clang::OverloadableAttr>()) { errors.push_back("Overloadable C adapters are not implemented: " + value->getQualifiedNameAsString()); }
			if (llvm::isa<clang::CXXMethodDecl>(function) || (context->getLangOpts().CPlusPlus && !function->isExternC())) {
				errors.push_back("C++ function adapters are not implemented: " + value->getQualifiedNameAsString());
			}
			result["kind"] = "function";
			const auto* symbol = function->getAttr<clang::AsmLabelAttr>();
			result["link_name"] = symbol ? symbol->getLabel().str() : function->getNameAsString();
			result["type"] = type(function->getType());
			result["returned_ownership"] = returnedOwnership(function);
			llvm::json::Array parameters;
			for (const auto* parameter : function->parameters()) {
				if (parameter->hasAttr<clang::PassObjectSizeAttr>()) { errors.push_back("Implicit native object-size parameters are not implemented: " + value->getQualifiedNameAsString()); }
				llvm::json::Object entry{{"name", parameter->getNameAsString()}, {"cf_consumed", parameter->hasAttr<clang::CFConsumedAttr>()}, {"ns_consumed", parameter->hasAttr<clang::NSConsumedAttr>()}};
				parameters.push_back(std::move(entry));
			}
			result["parameter_semantics"] = std::move(parameters);
		} else if (const auto* alias = llvm::dyn_cast<clang::TypedefNameDecl>(value)) {
			result["kind"] = "typedef";
			result["type"] = type(alias->getUnderlyingType(), alias->getUnderlyingType()->isIncompleteType());
		} else if (const auto* constant = llvm::dyn_cast<clang::EnumConstantDecl>(value)) {
			result["kind"] = "enum_constant";
			result["type"] = type(constant->getType());
			llvm::SmallString<32> decimal;
			constant->getInitVal().toString(decimal);
			result["value"] = decimal.str().str();
		} else if (const auto* record = llvm::dyn_cast<clang::RecordDecl>(value)) {
			result["kind"] = "record";
			result["type"] = type(context->getRecordType(record), record->getDefinition() == nullptr);
		} else {
			errors.push_back("Unsupported native declaration: " + value->getQualifiedNameAsString());
		}
		return result;
	}

public:
	explicit NativeHeaderReader(const std::vector<std::string>& symbols) : requested(symbols.begin(), symbols.end()) {}

	bool VisitNamedDecl(clang::NamedDecl* value) {
		auto name = value->getQualifiedNameAsString();
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
		for (const auto& name : requested) {
			auto found = declarations.find(name);
			if (found == declarations.end()) { errors.push_back("Native declaration not found: " + name); }
			else { exports.push_back(declaration(found->second)); }
		}
		if (errors.empty() && !value.getDiagnostics().hasErrorOccurred()) { readRecords(); }
		pendingRecords.clear();
		declarations.clear();
		context = nullptr;
	}

	bool publish() {
		if (!errors.empty()) {
			for (const auto& error : errors) { llvm::errs() << "error: " << error << '\n'; }
			return false;
		}
		llvm::json::Array layouts;
		for (auto& record : records) { layouts.push_back(std::move(record.second)); }
		llvm::json::Object document{{"schema", "btrc.native-declarations.experimental"}, {"target", target}, {"clang", clang::getClangFullVersion()}, {"big_endian", bigEndian}, {"character_bits", static_cast<int64_t>(characterBits)}, {"declarations", std::move(exports)}, {"records", std::move(layouts)}};
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

int main(int argc, const char** argv) {
	llvm::cl::OptionCategory category("BTRC native header reader");
	llvm::cl::list<std::string> symbols("symbol", llvm::cl::desc("Exact qualified declaration to read"), llvm::cl::OneOrMore, llvm::cl::cat(category));
	auto options = clang::tooling::CommonOptionsParser::create(argc, argv, category, llvm::cl::OneOrMore);
	if (!options) { llvm::errs() << options.takeError(); return 1; }
	if (options->getSourcePathList().size() != 1) { llvm::errs() << "error: expected exactly one native translation unit\n"; return 1; }
	NativeHeaderReader reader(std::vector<std::string>(symbols.begin(), symbols.end()));
	NativeHeaderActionFactory factory(reader);
	clang::tooling::ClangTool tool(options->getCompilations(), options->getSourcePathList());
	if (tool.run(&factory) != 0) { return 1; }
	return reader.publish() ? 0 : 1;
}
