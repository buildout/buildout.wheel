import distlib.wheel
import humpty
import os
import pkg_resources
import setuptools.package_index
from six.moves.urllib import parse
import wheel.install
import pip.pep425tags
import zc.buildout.easy_install

orig_interpret_distro_name = setuptools.package_index.interpret_distro_name
original_wheel_to_egg = zc.buildout.easy_install.wheel_to_egg

wheel_supported = pip.pep425tags.get_supported

def interpret_distro_name(
    location, basename, metadata, py_version=None,
    precedence=pkg_resources.SOURCE_DIST,
    platform=None
    ):
    if '.whl' in location:
        path = parse.urlparse(location).path
        try:
            wf = wheel.install.WheelFile(path, context=wheel_supported)
        except wheel.install.BadWheelFile:
            pass
        else:
            if wf.compatible:
                # It's a match. Treat it as a source
                # distro. Buildout will sort it out.
                assert wf.distinfo_name.endswith('.dist-info')
                return orig_interpret_distro_name(
                    location, wf.distinfo_name[:-10], metadata,
                    py_version=py_version,
                    # EGG_DIST since we want wheels to be prefered over source,
                    # and we'll turn them into eggs anyway:
                    precedence=pkg_resources.EGG_DIST,
                    platform=platform)
            else:
                # Not a match, short circuit:
                return ()
    return orig_interpret_distro_name(
        location, basename, metadata, py_version, precedence, platform)

def wheel_to_egg(dist, tmp):
    writer = humpty.EggWriter(dist.location)
    writer.build_egg(tmp)
    egg_name = writer.egg_name
    return pkg_resources.Distribution.from_location(
        os.path.join(tmp, egg_name), egg_name)

def load(buildout):
    setuptools.package_index.EXTENSIONS.append('.whl')
    setuptools.package_index.interpret_distro_name = interpret_distro_name
    distlib.wheel.COMPATIBLE_TAGS = set(wheel_supported())
    zc.buildout.easy_install.wheel_to_egg = wheel_to_egg
