class ImportFailure(Exception):
    """A whole document cannot be imported.

    The code is a fixed value that never contains file contents, so it is safe
    to store, display and log.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
