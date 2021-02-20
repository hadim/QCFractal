from __future__ import annotations
import logging
import sys
import logging.handlers
import gunicorn.app.base
from gunicorn.glogging import Logger as GLogger
from .flask_app import create_qcfractal_flask_app
from ..process_runner import ProcessBase

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..config import FractalConfig, Optional

#####################################################
# See https://docs.gunicorn.org/en/stable/custom.html
#####################################################
class FractalGunicornLogger(GLogger):
    def setup(self, cfg):
        # The base constructor messes with logging. So undo the important parts
        # of those changes. That way, all logging will be unified
        self.error_log = logging.getLogger("gunicorn.error")
        self.access_log = logging.getLogger("gunicorn.access")
        self.error_log.handlers = []
        self.access_log.handlers = []
        self.error_log.propagate = True
        self.access_log.propagate = True

class FractalGunicornApp(gunicorn.app.base.BaseApplication):

    def __init__(self,  qcfractal_config: FractalConfig):
        self.qcfractal_config = qcfractal_config
        self.application = create_qcfractal_flask_app(qcfractal_config)

        super().__init__()

    def load(self):
        return self.application

    def load_config(self):
        # This must be provided. It is called from the superclass, and we need to
        # populate self.cfg
        bind = self.qcfractal_config.flask.host
        port = self.qcfractal_config.flask.port

        config = {'bind': f'{bind}:{port}',
                  'workers': self.qcfractal_config.flask.num_workers,
                  'loglevel': self.qcfractal_config.loglevel,
                  'logger_class': FractalGunicornLogger
                  }

        for key, value in config.items():
            self.cfg.set(key.lower(), value)


class GunicornProcess(ProcessBase):
    """
    Gunicorn running in a separate process
    """

    def __init__(self, qcf_config: FractalConfig):
        ProcessBase.__init__(self)
        self.config = qcf_config

    def setup(self) -> None:
        self._gunicorn_app = FractalGunicornApp(self.config)

    def run(self) -> None:
        self._gunicorn_app.run()

    def interrupt(self) -> None:
        # Normally not reachable as gunicorn uses its own signal handlers. However,
        # may be reached if the process is interrupted during setup
        logging.getLogger(__name__).debug("Exiting gunicorn process")
        sys.exit(0)
