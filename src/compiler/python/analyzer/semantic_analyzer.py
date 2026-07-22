"""Semantic-analysis composition root."""

from .aggregate_contracts import AggregateContractsMixin
from .aggregate_layout import AggregateLayoutContractsMixin
from .array_contracts import ArrayContractsMixin
from .builtin_calls import BuiltinCallValidationMixin
from .call_arguments import CallArgumentBindingMixin
from .call_consumption import CallConsumptionContractsMixin
from .call_signatures import CallSignatureContractsMixin
from .call_targets import CallTargetContractsMixin
from .call_type_inference import CallTypeInferenceMixin
from .callable_values import CallableValueValidationMixin
from .calls import CallValidationMixin
from .cast_contracts import CastContractsMixin
from .constant_expressions import ConstantExpressionMixin
from .constructor_inference import ConstructorInferenceMixin
from .control_flow import ControlFlowAnalysisMixin
from .conversion_contracts import ConversionContractsMixin
from .core import AnalyzerBase
from .core_models import AnalyzedProgram
from .cycles import CycleAnalysisMixin
from .declaration_contracts import DeclarationContractsMixin
from .declaration_names import DeclarationNamesMixin
from .declaration_validation import RegisteredDeclarationValidationMixin
from .declarations.registry import DeclarationRegistry, DeclarationServices
from .enum_contracts import EnumContractsMixin
from .exceptions import ExceptionAnalysisMixin
from .expression_contracts import ExpressionContractsMixin
from .expression_ownership import ExpressionOwnershipContractsMixin
from .expressions import ExpressionsMixin
from .for_in_analysis import ForInAnalysisMixin
from .function_parameters import FunctionParameterContractsMixin
from .functions import FunctionsMixin
from .generated_symbols import GeneratedSymbolContractsMixin
from .generic_intrinsics import GenericIntrinsicValidationMixin
from .generic_methods import GenericMethodsMixin
from .generic_validation import GenericValidationMixin
from .gpu_array_contracts import GpuArrayContractsMixin
from .gpu_result_contexts import GpuResultContextContractsMixin
from .hierarchy import HierarchyValidationMixin
from .hosted_abi_contracts import HostedAbiContractsMixin
from .hosted_abi_declarations import HostedAbiDeclarationContractsMixin
from .hosted_result_contracts import HostedResultContractsMixin
from .identifier_contracts import IdentifierContractsMixin
from .index_expressions import IndexExpressionContractsMixin
from .indexed_updates import IndexedUpdateContractsMixin
from .initializers import InitializerValidationMixin
from .lambdas import LambdaAnalysisMixin
from .lvalue_contracts import LvalueContractsMixin
from .managed_rebinds import ManagedRebindContractsMixin
from .mutex_ownership import MutexOwnershipContractsMixin
from .node_type_storage import NodeTypeStorageMixin
from .nullable_control_flow import NullableControlFlowMixin
from .nullable_flow import NullableFlowMixin
from .occurrences import OccurrencesMixin
from .opaque_borrow_effects import OpaqueBorrowEffectsMixin
from .opaque_borrows import OpaqueBorrowContractsMixin
from .operator_inference import OperatorInferenceMixin
from .parameter_consumption import ParameterConsumptionContractsMixin
from .qualification import QualificationMixin
from .raw_deallocation import RawDeallocationContractsMixin
from .scalar_inference import ScalarInferenceMixin
from .source_macro_contracts import SourceMacroContractsMixin
from .statements import StatementsMixin
from .storage_contracts import StorageContractsMixin
from .storage_initializers import StorageInitializerContractsMixin
from .switch_contracts import SwitchContractsMixin
from .type_domains import TypeDomainContractsMixin
from .type_inference import TypeInferenceMixin
from .type_normalization import TypeNormalizationMixin
from .type_utils import TypeUtilsMixin
from .update_contracts import UpdateContractsMixin
from .validation import ValidationMixin
from .value_contracts import ValueContractsMixin
from .variable_declarations import VariableDeclarationAnalysisMixin


class SemanticAnalyzer(
    QualificationMixin,
    TypeUtilsMixin,
    ConversionContractsMixin,
    NodeTypeStorageMixin,
    ConstantExpressionMixin,
    StorageInitializerContractsMixin,
    AggregateContractsMixin,
    AggregateLayoutContractsMixin,
    ArrayContractsMixin,
    GpuArrayContractsMixin,
    GpuResultContextContractsMixin,
    CastContractsMixin,
    DeclarationNamesMixin,
    DeclarationContractsMixin,
    TypeDomainContractsMixin,
    StorageContractsMixin,
    HostedAbiDeclarationContractsMixin,
    HostedAbiContractsMixin,
    HostedResultContractsMixin,
    RegisteredDeclarationValidationMixin,
    EnumContractsMixin,
    OperatorInferenceMixin,
    ScalarInferenceMixin,
    ConstructorInferenceMixin,
    CallTypeInferenceMixin,
    TypeInferenceMixin,
    InitializerValidationMixin,
    IdentifierContractsMixin,
    CallTargetContractsMixin,
    CallableValueValidationMixin,
    GenericIntrinsicValidationMixin,
    BuiltinCallValidationMixin,
    CallArgumentBindingMixin,
    CallSignatureContractsMixin,
    ExpressionOwnershipContractsMixin,
    CallConsumptionContractsMixin,
    OpaqueBorrowEffectsMixin,
    OpaqueBorrowContractsMixin,
    RawDeallocationContractsMixin,
    CallValidationMixin,
    LvalueContractsMixin,
    IndexExpressionContractsMixin,
    IndexedUpdateContractsMixin,
    ManagedRebindContractsMixin,
    UpdateContractsMixin,
    ExpressionContractsMixin,
    ParameterConsumptionContractsMixin,
    MutexOwnershipContractsMixin,
    ValueContractsMixin,
    ExceptionAnalysisMixin,
    NullableFlowMixin,
    NullableControlFlowMixin,
    LambdaAnalysisMixin,
    SwitchContractsMixin,
    ForInAnalysisMixin,
    ControlFlowAnalysisMixin,
    TypeNormalizationMixin,
    CycleAnalysisMixin,
    HierarchyValidationMixin,
    GenericValidationMixin,
    GeneratedSymbolContractsMixin,
    ValidationMixin,
    GenericMethodsMixin,
    ExpressionsMixin,
    VariableDeclarationAnalysisMixin,
    StatementsMixin,
    SourceMacroContractsMixin,
    FunctionParameterContractsMixin,
    FunctionsMixin,
    OccurrencesMixin,
    AnalyzerBase,
):
    """Run semantic analysis with owned declaration registration."""

    def __init__(
        self,
        *,
        record_occurrences: bool = False,
        seed: AnalyzedProgram | None = None,
    ) -> None:
        super().__init__()
        self.record_occurrences = record_occurrences
        self.declarations = DeclarationRegistry(
            DeclarationServices(
                declarations=self._decls_with_file,
                error=self._error,
                validate_declared_name=self._validate_declared_name,
                validate_generic_parameter_names=self._validate_generic_parameter_names,
                validate_parameter_names=self._validate_parameter_names,
                validate_array_return_declaration=self._validate_array_return_declaration,
                validate_inherited_member_names=self._validate_inherited_member_names,
                hosted_type_declaration_allowed=self._hosted_type_declaration_allowed,
                hosted_object_declaration_allowed=self._hosted_object_declaration_allowed,
                function_declarations_compatible=self._function_declarations_compatible,
                merge_function_defaults=self._merge_function_defaults,
                global_scope=self.global_scope,
                current_source_file=lambda: self.current_source_file,
            ),
            seed=seed,
        )
        if seed is not None:
            self.generic_instances = {
                name: list(instances) for name, instances in seed.generic_instances.items()
            }


__all__ = ["SemanticAnalyzer"]
