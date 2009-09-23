import os

from paver.easy import *

import paver.virtual

options(
    virtualenv=Bunch(
        packages_to_install=['pip'],
        paver_command_line="setup"
    ),
    db=Bunch(
        wsgiscript=lambda: os.path.abspath("../wsgi-apps/bespin.wsgi")
    )
)

def _clean_up_extra_egg_info(d):
    """pip freeze has a problem with the extra egg-info directories
    that setuptools leaves lying around when you install using
    --single-version-externally-managed (which is what pip does).
    
    This does the simplest thing possible to fix this, which is to
    get rid of all but the last egg-info directory.
    
    The directory passed in should be the "lib" directory" which
    is above the pythonX.X/site-packages directory. This function
    will figure out which version of python is in use."""
    d = path(d)
    vi = sys.version_info
    d = d / ("python%s.%s" % (vi[0], vi[1])) / "site-packages"
    lastname = None
    lastf = None
    for f in d.glob("*.egg-info"):
        fullname = f.basename()
        pkgname = fullname.split("-", 1)[0]
        # check for a match against the previous
        if lastname == pkgname:
            # we have a match, so delete the previous which is
            # in theory an older version
            info("Deleting old egg-info: %s", lastf)
            lastf.rmtree()
        lastf = f
        lastname = pkgname

@task
def setup():
    """Get this production environment setup."""
    downloads = path("downloads")
    downloads.mkdir()
    os.environ["PIP_DOWNLOAD_CACHE"] = downloads.abspath()
    sh("bin/pip install -U -r requirements.txt")
    _clean_up_extra_egg_info("lib")
    print "Don't forget to run the database upgrade! (paver db)"
    
@task
def db(options):
    """Perform a database upgrade, if necessary.
    
    Your WSGI script is loaded in order to properly get the configuration
    set up. By default, the WSGI script is ../wsgi-apps/bespin.wsgi.
    You can override this on the command line like so:
    
    paver db.wsgiscript=/path/to/script.wsgi db
    """
    from bespin import config, model, db_versions
    from migrate.versioning.shell import main

    execfile(options.wsgiscript, {'__file__' : options.wsgiscript})
    
    repository = str(path(db_versions.__file__).dirname())
    dburl = config.c.dburl
    dry("Run the database upgrade", main, ["upgrade", dburl, repository])
    
    # touch the wsgi app so that mod_wsgi sees that we've updated
    sh("touch %s" % options.wsgiscript)

@task
def create_db():
    """Creates the production database.
    
    Your WSGI script is loaded in order to properly get the configuration
    set up. By default, the WSGI script is ../wsgi-apps/bespin.wsgi.
    You can override this on the command line like so:
    
    paver db.wsgiscript=/path/to/script.wsgi create_db
    """
    from bespin import config, database, db_versions
    from migrate.versioning.shell import main
    
    script = options.db.wsgiscript
    
    execfile(script, {'__file__' : script})

    dry("Create database tables", database.Base.metadata.create_all, bind=config.c.dbengine)
    
    repository = str(path(db_versions.__file__).dirname())
    dburl = config.c.dburl
    dry("Turn on migrate versioning", main, ["version_control", dburl, repository])
