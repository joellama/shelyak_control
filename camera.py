"""TODO."""

import pickle
import socketio
import sys
import time

from astropy.time import Time
import astropy.units as u
from tqdm.auto import trange
import numpy as np

# source and docs: https://github.com/python-zwoasi/python-zwoasi
import zwoasi as asi


class Camera:
    """TODO."""

    def __init__(self, device="/dev/cu.", simulator=False):
        """TODO."""
        if simulator:
            self.simulation = True
            self.device = None  # Replace with instance of K8056
            self.id = "5"
        else:
            self.simulation = False
            self.device = Zwocamera()
            self.id = sio.emit("get_id", "camera")

    def expose(self, request_input):
        """
        TODO.

        Args:
            nexp ():
            itime ():
        """
        if self.simulation:
            global continue_obs
            data: dict = {}

            nexp = request_input["num_exposures"]
            itime = request_input["exposure_duration"]

            continue_obs = True

            for kk in trange(int(nexp)):
                for jj in trange(int(itime)):
                    self.emit_status({"camera": "Busy"})

                    data = {
                        "obs_id": request_input["OBSID"],
                        "itime_elapsed": jj,
                        "itime_total": int(itime),
                        "exp_number": int(kk),
                        "nexp_total": int(nexp),
                    }

                    self.emit_status(data)

                    time.sleep(1)

                if continue_obs == False:
                    break

            self.emit_status({"camera": "Idle"})
            sio.emit("set_obs_type", 0)

            data = {
                "obs_id": request_input["OBSID"],
                "itime_elapsed": 0,
                "exp_number": 0,
                "itime_total": 1,
                "nexp_total": 1,
            }

            self.emit_status(data)

            # return type of exposure will be a one dim array from numpy.frombuffer()
            return []

    def return_image_data(self, image, request_input, tstart, tend):
        global global_data

        request_input["DATE-END"] = tend.fits
        request_input["DATE-OBS"] = tstart.fits
        request_input["EXPTIME"] = global_data["itime_total"]

        sio.emit("save_img", {"image": image, "exposure_data": request_input})

    def sequence(self, request_input):
        """
        TODO.

        Args:
            data ():
        """
        global global_data
        data: dict = {}

        num_exposures = int(request_input["num_exposures"])

        for kk in trange(int(num_exposures)):
            data = {
                "obs_id": request_input["OBSID"],
                "exp_number": int(kk),
                "nexp_total": int(num_exposures),
            }

            self.emit_status(data)

            tstart = Time.now()
            image = self.expose(request_input)
            tend = Time.now()

            time.sleep(1)
            self.return_image_data(image, request_input, tstart, tend)
            time.sleep(1)

        sio.emit("set_obs_type", 0)
        self.emit_status({"camera": "Finished"})

    def emit_status(self, status: dict) -> None:
        sio.emit("update_status", data=(self.id, status))


class Zwocamera:
    """
    TODO.

    Attributes:
        camera:
        camera_info:
    """

    def __init__(self, device="ZWO ASI2600MM Pro"):
        # TODO: remove
        env_filename = "../ASI_linux_mac_SDK_V1.28/lib/x64/libASICamera2.so.1.27"
        #  env_filename = "/Users/joellama/ASI_linux_mac_SDK_V1.28/lib/mac/libASICamera2.dylib"

        asi.init(env_filename)

        num_cameras = asi.get_num_cameras()

        if num_cameras == 0:
            print("No cameras found")
            sys.exit(0)

        cameras_found = asi.list_cameras()  # Models names of the connected cameras

        if num_cameras == 1:
            print("Found one camera: %s" % cameras_found[0])

        # In list of cameras, find index of given device
        try:
            idx = cameras_found.index(device)
        except ValueError:
            print(f"ERR: Couldn't find specified camera '{device}' in list of connected cameras. Exiting...")
            sys.exit(0)

        self.camera = asi.Camera(idx)
        self.camera_info = self.camera.get_camera_property()
        self.id = sio.call("get_instrument_id", device)
        self.exposure_terminated = False

        self.camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, self.camera.get_controls()["BandWidth"]["MinValue"])
        self.camera.disable_dark_subtract()

    # Helper Methods (private, internal usage only)
    @staticmethod
    def __convert_camera_status(status):
        if status == 0:
            return "Idle"
        elif status == 1:
            return "Busy"
        elif status == 2:
            return "Finished"
        else:
            return "Unknown"

    def __emit_status(self, status: dict) -> None:
        sio.emit("update_status", data=(self.id, status))

    def __get_camera_status_str(self) -> str:
        status = self.camera.get_exposure_status()
        return self.__convert_camera_status(status)

    # Public Methods
    def sequence(self, request_input):
        global global_data

        camera.exposure_terminated = False
        num_exposures = int(request_input["num_exposures"])
        exposure_duration = int(request_input["exposure_duration"])

        self.__emit_status({"nexp_total": num_exposures, "itime_total": exposure_duration})

        kk: int = 0

        while kk < num_exposures and not self.exposure_terminated:
            cur_status = {
                "obs_id": request_input["OBSID"],
                "exp_number": int(kk),
            }

            self.__emit_status(cur_status)

            tstart = Time.now()
            image = self.expose(exptime=exposure_duration)
            tend = Time.now()

            # FIXME: what does this do?
            #  sio.emit("get_next_file")

            if not self.exposure_terminated:
                time.sleep(1)
                self.return_image_data(image, request_input, tstart, tend)
                time.sleep(1)

            kk += 1

        #  update_global_vars({"ccd_status": 0})
        #  sio.emit("set_obs_type", 0)

        self.exposure_terminated = False
        self.conclude_observation()

    def expose(self, exptime=30):
        global global_data

        self.camera.set_control_value(asi.ASI_EXPOSURE, int(exptime * 1e6))
        self.camera.set_control_value(asi.ASI_GAIN, 46)
        self.camera.set_image_type(asi.ASI_IMG_RAW16)

        poll = 0.2
        initial_sleep = 1

        try:
            # Force any single exposure to be halted
            self.camera.stop_video_capture()
            self.camera.stop_exposure()
            time.sleep(initial_sleep)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            pass

        while self.camera.get_exposure_status() == asi.ASI_EXP_WORKING:
            # make sure we actually are not already exposing
            time.sleep(poll)

        self.camera.start_exposure()

        if initial_sleep:
            time.sleep(initial_sleep)

        #  tstart = Time.now()
        status = self.camera.get_exposure_status()

        while status == asi.ASI_EXP_WORKING:
            #  # FIXME: remove, will update itime on the frontend
            #  tnow = Time.now()
            #  tdiff = int((tnow - tstart).to(u.s).value)

            #  cur_status: dict = {
            #      "camera": self.__get_camera_status_str(),
            #      "itime_elapsed": tdiff,
            #  }

            #  self.__emit_status(cur_status)

            status = self.camera.get_exposure_status()

        self.__emit_status({"camera": self.__convert_camera_status(status), "itime_elapsed": 0})

        buffer_ = None
        data = self.camera.get_data_after_exposure(buffer_)

        self.__emit_status({"camera": self.__get_camera_status_str()})

        whbi = self.camera.get_roi_format()
        shape = [whbi[1], whbi[0]]

        if whbi[3] == asi.ASI_IMG_RAW8 or whbi[3] == asi.ASI_IMG_Y8:
            img = np.frombuffer(data, dtype=np.uint8)
        elif whbi[3] == asi.ASI_IMG_RAW16:
            img = np.frombuffer(data, dtype=np.uint16)
        elif whbi[3] == asi.ASI_IMG_RGB24:
            img = np.frombuffer(data, dtype=np.uint8)
            shape.append(3)
        else:
            raise ValueError("Unsupported image type")

        img = img.reshape(shape)

        self.__emit_status({"camera": self.__get_camera_status_str()})

        return img

    def return_image_data(self, image: np.ndarray, request_input, tstart, tend):
        global global_data

        request_input["DATE-END"] = tend.fits
        request_input["DATE-OBS"] = tstart.fits
        request_input["IMAGETYP"] = self.camera.get_image_type()
        request_input["CCD-TEMP"] = self.camera.get_image_type()

        for k, v in self.camera.get_control_values().items():
            request_input[k.upper()[:8]] = v

        sio.emit("save_img", data=(pickle.dumps(image), request_input))

    def conclude_observation(self):
        self.__emit_status(
            {
                "exp_number": 0,
                "exp_number": 0,
                "itime_elapsed": 0,
                "itime_elapsed": 0,
                "nexp_total": 0,
            }
        )

        sio.emit("observation_complete")


if __name__ == "__main__":
    sio = socketio.Client(
        request_timeout=60,
        logger=True,
        engineio_logger=True,
    )
    sio.connect("http://localhost:5000")
    camera = Zwocamera(device="ZWO ASI120MM-S")

    global_data = {}

    @sio.on("begin_exposure")
    def sequence(obs_request):
        camera.sequence(obs_request)

    @sio.event
    def disconnect():
        sio.emit("observation_complete")

    @sio.on("end_exposure")
    def end_exp():
        camera.exposure_terminated = True

        try:
            camera.camera.stop_exposure()
        except:
            pass
