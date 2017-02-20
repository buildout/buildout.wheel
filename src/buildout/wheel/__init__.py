import distlib.wheel
import humpty
import os
import pkg_resources
import setuptools.package_index
import wheel.install
import wheel.decorator
import pip.pep425tags
import zc.buildout.easy_install

orig_distros_for_location = setuptools.package_index.distros_for_location
original_wheel_to_egg = zc.buildout.easy_install.wheel_to_egg

wheel_supported = pip.pep425tags.get_supported
class WheelFile(wheel.install.WheelFile):

    def __init__(self, *args, **kwargs):
        # use pip's notion of supported tags, not wheel's:
        kwargs.setdefault('context', pip.pep425tags.get_supported)
        super(WheelFile, self).__init__(*args, **kwargs)

    @wheel.decorator.reify
    def is_platform_specific(self):
        return (self.parsed_filename.group('abi') != 'none' or
                self.parsed_filename.group('plat') != 'any')


    @wheel.decorator.reify
    def egg_platform(self):
        if self.compatible and self.is_platform_specific:
            # pretend we're a perfect match to avoid issues
            # TODO: is this really necessary for buildout? Will buildout ignore
            # manylinux1_x86_64 eggs in it's own eggs directory?
            return pkg_resources.get_build_platform()
        else:
            plat = self.parsed_filename.group('plat')
            return plat if plat != 'any' else None

    def distribution(self, location=None, metadata=None,
                     class_=pkg_resources.Distribution):
        parsed = self.parsed_filename.groupdict()
        return class_(
            location=location if location is not None else self.filename,
            metadata=metadata,
            project_name=parsed['name'],
            version=parsed['ver'],
            platform=self.egg_platform,
        )

def distros_for_location(location, basename, metadata=None):
    """Yield egg or source distribution objects based on basename

    Here we override to give wheels a chance"""
    if basename.endswith('.whl'):
        try:
            wf = WheelFile(basename)
        except wheel.install.BadWheelFile:
            pass
        else:
            if wf.compatible:
                # It's a match. Treat it as an egg
                # distro. Buildout will sort it out.
                return [wf.distribution(location, metadata)]
        # Not a match, short circuit:
        return ()
    return orig_distros_for_location(location, basename, metadata=metadata)

def wheel_to_egg(dist, tmp):
    writer = humpty.EggWriter(dist.location)
    writer.build_egg(tmp)
    egg_name = writer.egg_name
    return pkg_resources.Distribution.from_location(
        os.path.join(tmp, egg_name), egg_name)

def load(buildout):
    distlib.wheel.COMPATIBLE_TAGS = set(wheel_supported())
    setuptools.package_index.distros_for_location = distros_for_location
    zc.buildout.easy_install.wheel_to_egg = wheel_to_egg
