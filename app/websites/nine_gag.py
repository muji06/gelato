import ffmpeg
import logging
import tempfile

from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL

from websites.base import Base

logger = logging.getLogger(__name__)

class NineGAG(Base):
    yt_params: dict[str,bool|str|int]= {
        "quiet": True,
        "no_warnings": True,
        "geo_bypass": True,
        "overwrites": True,
    }
    convert_to_mp4 = True
    
    def download_video(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            output_name = temp_file.name
            self.output_path.append(output_name)

        self.yt_params["outtmpl"]= output_name
        # download video
        with YoutubeDL(self.yt_params) as foo:
            foo.download([self.download_url])


    def convert_video(self):
        input_file = self.output_path[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            output_name = temp_file.name
            self.output_path.append(output_name)

        (ffmpeg
        .input(input_file)
        .output(output_name, f='mp4', vcodec=self._ffmpeg_codec)
        .overwrite_output()
        .run())
