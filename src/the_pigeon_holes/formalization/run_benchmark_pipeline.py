"""Run formalization, proof generation, and Lean verification with CSV metrics."""

import argparse

from .benchmark import run_benchmark
from .generate_benchmark import generate
from .generate_validation import generate_validations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--limit", type=int, default=10,
                        help="unique problems (default: 10; use 0 for all)")
    parser.add_argument("--force", action="store_true",
                        help="rerun paid stages even when artifacts already exist")
    args = parser.parse_args()
    limit = None if args.limit == 0 else args.limit
    generate(args.split, limit, args.force)
    generate_validations(args.split, limit, args.force)
    run_benchmark(args.split)


if __name__ == "__main__":
    main()
