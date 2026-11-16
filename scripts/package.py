"""Compatibility entry point for the fixed reviewed source release builder."""
from release import main

if __name__=="__main__":
    raise SystemExit(main(["build"]))
