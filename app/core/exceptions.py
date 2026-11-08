class DocumentProcessingError(Exception):
    """Raised when parsing or extracting raw document contents fails."""
    pass

class CorruptedFileError(DocumentProcessingError):
    """Raised when an uploaded file cannot be parsed or decoded."""
    pass

class ExtractionError(Exception):
    """Raised when AI information extraction fails."""
    pass

class ValidationError(Exception):
    """Raised when validation engine encounters fatal rule check issues."""
    pass
