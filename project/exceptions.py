class SampleError(Exception):
    """Sample exception used to verify error reporting."""

    def __init__(self) -> None:
        """Initialize the sample error with a fixed message."""
        super().__init__('Sample error')
