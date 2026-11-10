class HomeworksException(Exception):
    pass


class HomeworksConnectionFailed(HomeworksException):
    pass


class HomeworksConnectionLost(HomeworksException):
    pass


class HomeworksTimeout(HomeworksException):
    """No matching reply arrived before the timeout."""

    def __init__(self, command: str) -> None:
        """Store the command that got no reply."""
        super().__init__(f"No reply to {command}")
        self.command = command


class HomeworksAuthenticationException(HomeworksException):
    pass


class HomeworksNoCredentialsProvided(HomeworksAuthenticationException):
    pass


class HomeworksInvalidCredentialsProvided(HomeworksAuthenticationException):
    pass
