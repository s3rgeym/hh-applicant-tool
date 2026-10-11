class Error(Exception):
    pass


# Используй эту ошибку для прерывания выполнения команд
class OperationError(Error):
    pass


class OperationCanceled(OperationError):
    pass
