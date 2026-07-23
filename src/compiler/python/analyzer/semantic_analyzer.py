"""Semantic-analysis composition root."""

from ..numeric_literals import NumericLiteralSemantics
from .aggregate_contracts import AggregateContractsMixin
from .aggregate_layout import AggregateLayoutContractsMixin
from .analysis_context import AnalysisContext
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
from .declaration_validation import RegisteredDeclarationValidationMixin
from .declarations.registry import DeclarationRegistry
from .enum_contracts import EnumContractsMixin
from .exceptions import ExceptionAnalysisMixin
from .expression_contracts import ExpressionContractsMixin
from .expression_ownership import ExpressionOwnershipContractsMixin
from .expressions import ExpressionsMixin
from .for_in_analysis import ForInAnalysisMixin
from .functions import FunctionsMixin
from .generated_symbols import GeneratedSymbolContractsMixin
from .generic_intrinsics import GenericIntrinsicValidationMixin
from .generic_methods import GenericMethodsMixin
from .generic_validation import GenericValidationMixin
from .gpu import GpuKernelValidator
from .gpu_dispatch import GpuDispatchValidator
from .hierarchy_validator import HierarchyValidator
from .hosted_abi_contracts import HostedAbiContractsMixin
from .hosted_result_contracts import HostedResultContractsMixin
from .identifier_contracts import IdentifierContractsMixin
from .index_expressions import IndexExpressionContractsMixin
from .indexed_updates import IndexedUpdateContractsMixin
from .initializer_analyzer import InitializerAnalyzer, InitializerTypeLayout
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
    CastContractsMixin,
    TypeDomainContractsMixin,
    StorageContractsMixin,
    HostedAbiContractsMixin,
    HostedResultContractsMixin,
    RegisteredDeclarationValidationMixin,
    EnumContractsMixin,
    OperatorInferenceMixin,
    ScalarInferenceMixin,
    ConstructorInferenceMixin,
    CallTypeInferenceMixin,
    TypeInferenceMixin,
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
    GenericValidationMixin,
    GeneratedSymbolContractsMixin,
    ValidationMixin,
    GenericMethodsMixin,
    ExpressionsMixin,
    VariableDeclarationAnalysisMixin,
    StatementsMixin,
    SourceMacroContractsMixin,
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
        numeric_literals: NumericLiteralSemantics | None = None,
    ) -> None:
        context = AnalysisContext()
        literal_semantics = numeric_literals if numeric_literals is not None else NumericLiteralSemantics()
        super().__init__(context, literal_semantics)
        self.record_occurrences = record_occurrences
        self.declarations = DeclarationRegistry(
            context,
            self.global_scope,
            seed=seed,
        )
        self.declaration_policy = self.declarations.policy
        self.gpu_dispatch = GpuDispatchValidator(
            context,
            self.declarations,
            canonical_type=self._canonical_type,
            analyze_expression=self._analyze_expr,
        )
        self.gpu_kernels = GpuKernelValidator(
            context,
            self.declarations,
            self.node_types,
            literal_semantics,
        )
        self.initializers = InitializerAnalyzer(
            context,
            self.declarations,
            InitializerTypeLayout(self.declarations),
        )
        self.hierarchy = HierarchyValidator(
            context,
            self.declarations,
            self.declaration_policy.signatures,
        )
        if seed is not None:
            self.generic_instances = {name: list(instances) for name, instances in seed.generic_instances.items()}


__all__ = ["SemanticAnalyzer"]
