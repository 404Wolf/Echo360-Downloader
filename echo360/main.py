import argparse
from sys import version_info
import os
import sys
import re
import logging
import time
import selenium
from selenium.common.exceptions import InvalidArgumentException
from datetime import datetime
from .echo_exceptions import EchoLoginError
from .course import EchoCourse, EchoCloudCourse
from .downloader import EchoDownloader

_DEFAULT_OUTPUT_PATH = "./out"
_DEFAULT_BEFORE_DATE = datetime(2900, 1, 1).date()
_DEFAULT_AFTER_DATE = datetime(1100, 1, 1).date()

_LOGGER = logging.getLogger(__name__)


def try_parse_date(date_string, fmt):
    try:
        return datetime.strptime(date_string, fmt).date()
    except ValueError:
        print("Error parsing date input:", sys.exc_info())
        sys.exit(1)


def handle_args():
    parser = argparse.ArgumentParser(description="Download lectures from  portal.")
    parser.add_argument(
        "url",
        help="Full URL of the echo360 course page, \
              or only the UUID (which defaults to USYD). \
              The URL of the course's video lecture page, \
              for example: http://recordings.engineering.illinois.edu/ess/portal/section/115f3def-7371-4e98-b72f-6efe53771b2a)",  # noqa
        metavar="ECHO360_URL",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Path to the desired output directory. The output \
                             directory must exist. Otherwise the current \
                             directory is used.",
        metavar="OUTPUT_PATH",
    )
    parser.add_argument(
        "--after-date",
        dest="after_date",
        help="Only download lectures newer than AFTER_DATE \
                             (inclusive). Note: this may be combined with \
                             --before-date.",
        metavar="AFTER_DATE(YYYY-MM-DD)",
    )
    parser.add_argument(
        "--before-date",
        dest="before_date",
        help="Only download lectures older than BEFORE_DATE \
                              (inclusive). Note: this may be combined with \
                              --after-date",
        metavar="BEFORE_DATE(YYYY-MM-DD)",
    )
    parser.add_argument(
        "--echo360cloud",
        action="store_true",
        default=False,
        help="Treat the given hostname as echo360 cloud platform.",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        default=False,
        help="Interactively pick the lectures you want, instead of download all \
                              (default) or based on dates .",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        dest="enable_degbug",
        help="Enable extensive logging.",
    )

    redirection_option = parser.add_mutually_exclusive_group(required=False)
    redirection_option.add_argument(
        "--auto",
        action="store_true",
        help="Only effective for 'echo360.org' host. When set, this script will attempts to \
                              automatically redirects after you had logged into your \
                              institution's SSO.",
    )

    args = vars(parser.parse_args())
    course_url = args["url"]

    course_hostname = re.search(
        "https?:[/]{2}[^/]*", course_url
    )  # would be none if it does not exists
    if course_hostname is not None:
        course_hostname = course_hostname.group()
    else:
        _LOGGER.info(
            "Non-URL value is given, defaults to University of Sydney's echo system"
        )
        _LOGGER.info("Use the full URL if you want to use this in other University")

    output_path = (
        os.path.expanduser(args["output"])
        if args["output"] is not None
        else _DEFAULT_OUTPUT_PATH
    )
    os.makedirs(output_path, exist_ok=True)
    output_path = output_path if os.path.isdir(output_path) else _DEFAULT_OUTPUT_PATH

    after_date = (
        try_parse_date(args["after_date"], "%Y-%m-%d")
        if args["after_date"]
        else _DEFAULT_AFTER_DATE
    )
    before_date = (
        try_parse_date(args["before_date"], "%Y-%m-%d")
        if args["before_date"]
        else _DEFAULT_BEFORE_DATE
    )

    return (
        course_url,
        course_hostname,
        output_path,
        after_date,
        before_date,
        args["interactive"],
        args["enable_degbug"],
        args["echo360cloud"],
    )


def main():
    (
        course_url,
        course_hostname,
        output_path,
        after_date,
        before_date,
        interactive_mode,
        enable_degbug,
        usingEcho360Cloud,
    ) = handle_args()

    setup_logging(enable_degbug)

    if not usingEcho360Cloud and any(
        token in course_hostname  # pyright: ignore
        for token in ["echo360.org", "echo360.net"]
    ):
        print("> Echo360 Cloud platform detected")
        print("> This implies setup_credential, and using web_driver")
        print(">> Please login with your SSO details and press enter when logged in.")
        print("-" * 65)
        usingEcho360Cloud = True

    if usingEcho360Cloud:
        # echo360 cloud
        course_uuid = re.search("[^/]([0-9a-zA-Z]+[-])+[0-9a-zA-Z]+", course_url)
        if course_uuid is None:
            raise ValueError("Invalid URL")
        course_uuid = course_uuid.group()  # retrieve the last part of the URL
        course = EchoCloudCourse(course_uuid, course_hostname)
    else:
        # import it here for monkey patching gevent, to fix the followings:
        # MonkeyPatchWarning: Monkey-patching ssl after ssl has already been
        # imported may lead to errors, including RecursionError on Python 3.6.
        from . import hls_downloader

        course_uuid = re.search("[^/]+(?=/$|$)", course_url)
        if course_uuid is None:
            raise ValueError("Invalid URL")
        course_uuid = course_uuid.group()  # retrieve the last part of the URL
        course = EchoCourse(course_uuid, course_hostname)
    downloader = EchoDownloader(
        course,
        output_path,
        date_range=(after_date, before_date),
        interactive_mode=interactive_mode,
    )

    downloader._driver.get(course_url)
    print(" >> After you finished logging in press enter in the terminal.")
    input()
    try:
        downloader._driver.set_window_size(0, 0)
        raise InvalidArgumentException()
    except InvalidArgumentException:
        # fallback to default size
        # see https://github.com/soraxas/echo360/issues/50
        downloader._driver.set_window_size(800, 600)
    downloader.download_all()


def setup_logging(enable_degbug=False):
    # set up logging to file - see previous section for more details
    logging_level = logging.DEBUG if enable_degbug else logging.INFO
    log_path = "echo360Downloader.log"
    logging.basicConfig(
        level=logging_level,
        format="[%(levelname)s: %(asctime)s] %(name)-12s %(message)s",
        datefmt="%m-%d %H:%M",
        filename=log_path,
        filemode="w",
    )
    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler()
    console.setLevel(logging_level)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logging.getLogger("").addHandler(console)  # add handler to the root logger
