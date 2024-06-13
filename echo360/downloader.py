import dateutil.parser
import os
import sys
import logging
import re

from .course import EchoCloudCourse
from .echo_exceptions import EchoLoginError


from pick import pick
import selenium
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options

_LOGGER = logging.getLogger(__name__)


def build_firefox_driver(user_agent, log_path) -> webdriver.Firefox:
    profile = webdriver.FirefoxProfile()
    profile.set_preference("general.useragent.override", user_agent)
    kwargs = dict()

    option = Options()
    option.profile = profile

    return webdriver.Firefox(
        service=Service(**kwargs, log_file=log_path),
        options=option,
    )


class EchoDownloader(object):
    def __init__(
        self,
        course,
        output_dir,
        date_range,
        interactive_mode=False,
    ):
        self._course = course
        root_path = "."
        if output_dir == "":
            output_dir = root_path
        self._output_dir = output_dir
        self._date_range = date_range
        self.interactive_mode = interactive_mode

        self.regex_replace_invalid = re.compile(r"[\\\\/:*?\"<>|]")

        # define a log path for phantomjs to output, to prevent hanging due to PIPE being full
        log_path = os.path.join(root_path, "webdriver_service.log")

        self._useragent = "Mozilla/5.0 (iPad; CPU OS 6_0 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A5376e Safari/8536.25"

        self._driver = build_firefox_driver(
            user_agent=self._useragent,
            log_path=log_path,
        )
        self._course.set_driver(self._driver)
        self._videos = []

    def download_all(self):
        sys.stdout.write('>> Logging into "{0}"... '.format(self._course.url))
        sys.stdout.flush()
        sys.stdout.write(">> Retrieving echo360 Course Info... ")
        sys.stdout.flush()
        videos = self._course.get_videos().videos
        print("Done!")
        # change the output directory to be inside a folder named after the course
        self._output_dir = os.path.join(
            self._output_dir, "{0}".format(self._course.nice_name).strip()
        )
        # replace invalid character for folder
        self.regex_replace_invalid.sub("_", self._output_dir)

        filtered_videos = [video for video in videos if self._in_date_range(video.date)]
        videos_to_be_download = []
        for video in reversed(filtered_videos):  # reverse so we download newest first
            lecture_number = self._find_pos(videos, video)
            # Sometimes a video could have multiple part. This special method returns a
            # generator where: (i) if it's a multi-part video it will contains multiple
            # videos and (ii) if it is NOT a multi-part video, it will just
            # returns itself
            sub_videos = video.get_all_parts()
            for sub_i, sub_video in reversed(list(enumerate(sub_videos))):
                sub_lecture_num = lecture_number + 1
                # use a friendly way to name sub-part lectures
                if len(sub_videos) > 1:
                    sub_lecture_num = "{}.{}".format(sub_lecture_num, sub_i + 1)
                title = "Lecture {} [{}]".format(sub_lecture_num, sub_video.title)
                filename = self._get_filename(
                    self._course.course_id, sub_video.date, title
                )
                videos_to_be_download.append((filename, sub_video))
        if self.interactive_mode:
            title = (
                "Select video(s) to be downloaded (SPACE to mark, ENTER to continue):"
            )
            selected = pick(
                [v[0] for v in videos_to_be_download],
                title,
                multiselect=True,
                min_selection_count=1,
            )
            videos_to_be_download = [videos_to_be_download[s[1]] for s in selected]

        print("=" * 60)
        print("    Course: {0}".format(self._course.nice_name))
        print(
            "      Total videos to download: {0} out of {1}".format(
                len(videos_to_be_download), len(videos)
            )
        )
        print("=" * 60)

        downloaded_videos = []
        for filename, video in videos_to_be_download:
            if video.url is False:
                print(
                    ">> Skipping Lecture '{0}' as it says it does "
                    "not contain any video.".format(filename)
                )
            else:
                if video.download(self._output_dir, filename):
                    downloaded_videos.insert(0, filename)
        print(self.success_msg(self._course.course_name, downloaded_videos))
        self._driver.close()

    @property
    def useragent(self):
        return self._useragent

    @useragent.setter
    def useragent(self, useragent):
        self._useragent = useragent

    def _initialize(self, echo_course):
        self._driver.get(self._course.url)

    def _get_filename(self, course, date, title):
        if course:
            # add [:150] to avoid filename too long exception
            filename = "{} - {} - {}".format(course, date, title[:150])
        else:
            filename = "{} - {}".format(date, title[:150])
        # replace invalid character for files
        return self.regex_replace_invalid.sub("_", filename)

    def _in_date_range(self, date_string):
        the_date = dateutil.parser.parse(date_string).date()
        return self._date_range[0] <= the_date and the_date <= self._date_range[1]

    def _find_pos(self, videos, the_video):
        # compare by object id, because date could possibly be the same in some case.
        return videos.index(the_video)

    def success_msg(self, course_name, videos):
        bar = "=" * 65
        msg = "\n{0}\n".format(bar)
        msg += "    Course: {0}".format(self._course.nice_name)
        msg += "\n{0}\n".format(bar)
        msg += "    Successfully downloaded:\n"
        for i in videos:
            msg += "        {}\n".format(i)
        msg += "{0}\n".format(bar)
        return msg

    def find_element_by_partial_id(self, id):
        try:
            return self._driver.find_element(
                By.XPATH, "//*[contains(@id,'{0}')]".format(id)
            )
        except NoSuchElementException:
            return None

    def retrieve_real_uuid(self):
        # patch for cavas (canvas.sydney.edu.au) where uuid is hidden in page source
        # we detect it by trying to retrieve the real uuid
        uuid = re.search(
            "/ess/client/section/([0-9a-zA-Z]{8}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{12})",
            self._driver.page_source,
        )
        if uuid is not None:
            uuid = uuid.groups()[0]
            self._course._uuid = uuid
