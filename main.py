import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from promptpop.app import main


def _entry():
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        try:
            from promptpop.config import config_dir
            log = config_dir() / "crash.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n==== crash %s ====\n"
                        % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exc(file=f)
        except Exception:
            pass
        traceback.print_exc()
        raise


if __name__ == "__main__":
    _entry()
