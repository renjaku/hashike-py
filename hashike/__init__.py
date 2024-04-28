__version__ = '0.0.0'

from .cli import main
from .core import ApplyResult, Context, apply

__all__ = ['ApplyResult', 'Context', 'apply']

if __name__ == '__main__':
    main()
