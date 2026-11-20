"""Start the combined Translation Tools desktop app."""
import argparse
from translation_tools.gui import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="File renaming and subtitle timing utilities")
    parser.add_argument("--tab", choices=["renamer", "timestamps"], default="renamer")
    args = parser.parse_args()
    main(args.tab)
