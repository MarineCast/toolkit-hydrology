"""Compatibility imports; implementation lives in utils.http."""

from .utils.http import AuthenticationError as AuthenticationError
from .utils.http import Client as Client
from .utils.http import ProviderError as ProviderError
from .utils.http import RequestDeferred as RequestDeferred
from .utils.http import UnsupportedVariable as UnsupportedVariable
from .utils.http import retry_after_deadline as retry_after_deadline
