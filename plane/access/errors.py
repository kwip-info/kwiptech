class Problem(Exception):
    def __init__(self, code, message, status=400, **details):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)
