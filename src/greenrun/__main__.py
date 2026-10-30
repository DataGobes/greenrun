import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="greenrun")
    commands = parser.add_subparsers(dest="command", title="commands")

    ingest = commands.add_parser("ingest", help="load raw data into the warehouse")
    sources = ingest.add_subparsers(dest="source", title="sources", required=True)
    weather_cmd = sources.add_parser("weather", help="hourly weather for DE-LU from Open-Meteo")
    weather_cmd.add_argument("--start", required=True, help="first day, YYYY-MM-DD (inclusive)")
    weather_cmd.add_argument("--end", required=True, help="last day, YYYY-MM-DD (inclusive)")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "ingest" and args.source == "weather":
        from greenrun import weather

        return weather.run_ingest(args.start, args.end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
