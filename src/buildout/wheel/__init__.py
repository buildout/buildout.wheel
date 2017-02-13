import distlib.wheel
import humpty
import os
import pkg_resources
import setuptools.package_index
from six.moves.urllib import parse
import wheel.install
import wheel.pep425tags
import zc.buildout.easy_install

orig_interpret_distro_name = setuptools.package_index.interpret_distro_name
original_wheel_to_egg = zc.buildout.easy_install.wheel_to_egg

class EggWriter(humpty.EggWriter):

    def __init__(self, wheel_file):
        wheel = distlib.wheel.Wheel(wheel_file)
        # Distlib gets this wrong on Mac:
        # assert wheel.is_compatible(), \
        #     "%s is not compatible with this platform" % wheel_file
        wheel.verify()

        self.wheel = wheel

wheel_supported = wheel.pep425tags.get_supported()

def interpret_distro_name(
    location, basename, metadata, py_version=None,
    precedence=pkg_resources.SOURCE_DIST,
    platform=None
    ):
    if '.whl' in location:
        path = parse.urlparse(location).path
        try:
            wf = wheel.install.WheelFile(path)
        except wheel.install.BadWheelFile:
            pass
        else:
            rank = wf.compatibility_rank(wheel_supported)
            if rank[0] < len(wheel_supported):
                # It's a match. Treat it as a source
                # distro. Buildout will sort it out.
                assert wf.distinfo_name.endswith('.dist-info')
                return orig_interpret_distro_name(
                    location, wf.distinfo_name[:-10], metadata,
                    py_version=py_version,
                    precedence=3, # 0 because we want wheels to be
                                  # prefered over source
                    platform=platform)
            else:
                # Not a match, short circuit:
                return ()
    return orig_interpret_distro_name(
        location, basename, metadata, py_version, precedence, platform)

def wheel_to_egg(dist, tmp):
    writer = EggWriter(dist.location)
    writer.build_egg(tmp)
    egg_name = writer.egg_name
    return pkg_resources.Distribution.from_location(
        os.path.join(tmp, egg_name), egg_name)

def load(buildout):
    setuptools.package_index.EXTENSIONS.append('.whl')
    setuptools.package_index.interpret_distro_name = interpret_distro_name
    zc.buildout.easy_install.wheel_to_egg = wheel_to_egg
