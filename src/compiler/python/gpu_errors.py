"""Stable host/GPU status codes for checked kernel operations."""

GPU_STATUS_BOUNDS = 1
GPU_STATUS_DIV_ZERO = 2
GPU_STATUS_MOD_ZERO = 3
GPU_STATUS_DIV_OVERFLOW = 4

GPU_UNKNOWN_STATUS_MESSAGE = "[btrc-gpu] GPU kernel reported an unknown failure status\n"
GPU_TRANSFER_FAILURE_MESSAGE = "[btrc-gpu] GPU dispatch or result transfer failed after submission\n"

GPU_STATUS_MESSAGES = {
    GPU_STATUS_BOUNDS: "GPU array index out of bounds\n",
    GPU_STATUS_DIV_ZERO: "Division by zero\n",
    GPU_STATUS_MOD_ZERO: "Modulo by zero\n",
    GPU_STATUS_DIV_OVERFLOW: "Integer division overflow\n",
}
