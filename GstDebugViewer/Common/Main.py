# -*- coding: utf-8; mode: python; -*-
#
#  GStreamer Development Utilities
#
#  Copyright (C) 2007 René Stadler <mail@renestadler.de>
#
#  This program is free software; you can redistribute it and/or modify it
#  under the terms of the GNU General Public License as published by the Free
#  Software Foundation; either version 3 of the License, or (at your option)
#  any later version.
#
#  This program is distributed in the hope that it will be useful, but WITHOUT
#  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
#  FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
#  more details.
#
#  You should have received a copy of the GNU General Public License along with
#  this program.  If not, see <http://www.gnu.org/licenses/>.

"""GStreamer Development Utilities Common Main module."""

import sys
import os
import traceback
from operator import attrgetter
import logging
import locale
import gettext
from gettext import gettext as _, ngettext

import pygtk
pygtk.require ("2.0")
del pygtk

import gobject

class ExceptionHandler (object):

    exc_types = (Exception,)
    priority = 50
    inherit_fork = True

    _handling_exception = False

    def __call__ (self, exc_type, exc_value, exc_traceback):

        raise NotImplementedError ("derived classes need to override this method")

class DefaultExceptionHandler (ExceptionHandler):

    # TODO Py2.5: In Python 2.5, this succeeds.  Remove the try...except block
    # once we depend on 2.5.
    try:
        exc_types = (BaseException,)
    except NameError:
        # Python < 2.5.
        exc_types = (Exception,)
    priority = 0
    inherit_fork = True

    def __init__ (self, excepthook):

        ExceptionHandler.__init__ (self)

        self.excepthook = excepthook

    def __call__ (self, *exc_info):

        return self.excepthook (*exc_info)

class ExitOnInterruptExceptionHandler (ExceptionHandler):

    exc_types = (KeyboardInterrupt,)
    priority = 100
    inherit_fork = False

    exit_status = 2

    def __call__ (self, *args):

        print >> sys.stderr, "Interrupt caught, exiting."

        sys.exit (self.exit_status)

class MainLoopWrapper (ExceptionHandler):

    priority = 95
    inherit_fork = False

    def __init__ (self, enter, exit):

        ExceptionHandler.__init__ (self)

        self.exc_info = (None,) * 3
        self.enter = enter
        self.exit = exit

    def __call__ (self, *exc_info):

        self.exc_info = exc_info
        self.exit ()

    def run (self):

        ExceptHookManager.register_handler (self)
        try:
            self.enter ()
        finally:
            ExceptHookManager.unregister_handler (self)

        if self.exc_info != (None,) * 3:
            # Re-raise unhandled exception that occured while running the loop.
            exc_type, exc_value, exc_tb = self.exc_info
            raise exc_type, exc_value, exc_tb

class ExceptHookManagerClass (object):

    def __init__ (self):

        self._in_forked_child = False

        self.handlers = []

    def setup (self):

        if sys.excepthook == self.__excepthook:
            raise ValueError ("already set up")

        hook = sys.excepthook
        self.__instrument_excepthook ()
        self.__instrument_fork ()
        self.register_handler (DefaultExceptionHandler (hook))

    def shutdown (self):

        if sys.excepthook != self.__excepthook:
            raise ValueError ("not set up")

        self.__restore_excepthook ()
        self.__restore_fork ()

    def __instrument_excepthook (self):

        hook = sys.excepthook
        self._original_excepthook = hook
        sys.excepthook = self.__excepthook

    def __restore_excepthook (self):

        sys.excepthook = self._original_excepthook

    def __instrument_fork (self):

        try:
            fork = os.fork
        except AttributeError:
            # System has no fork() system call.
            self._original_fork = None
        else:
            self._original_fork = fork
            os.fork = self.__fork

    def __restore_fork (self):

        if not hasattr (os, "fork"):
            return

        os.fork = self._original_fork

    def entered_forked_child (self):

        self._in_forked_child = True

        for handler in tuple (self.handlers):
            if not handler.inherit_fork:
                self.handlers.remove (handler)

    def register_handler (self, handler):

        if self._in_forked_child and not handler.inherit_fork:
            return

        self.handlers.append (handler)

    def unregister_handler (self, handler):

        self.handlers.remove (handler)

    def __fork (self):

        pid = self._original_fork ()
        if pid == 0:
            # Child process.
            self.entered_forked_child ()
        return pid

    def __excepthook (self, exc_type, exc_value, exc_traceback):

        for handler in sorted (self.handlers,
                               key = attrgetter ("priority"),
                               reverse = True):

            if handler._handling_exception:
                continue

            for type_ in handler.exc_types:
                if issubclass (exc_type, type_):
                    break
            else:
                continue

            handler._handling_exception = True
            handler (exc_type, exc_value, exc_traceback)
            # Not using try...finally on purpose here.  If the handler itself
            # fails with an exception, this prevents recursing into it again.
            handler._handling_exception = False
            return

        else:
            from warnings import warn
            warn ("ExceptHookManager: unhandled %r" % (exc_value,),
                  RuntimeWarning,
                  stacklevel = 2)

ExceptHookManager = ExceptHookManagerClass ()

class PathsBase (object):

    data_dir = None
    icon_dir = None
    locale_dir = None

    @classmethod
    def setup_installed (cls, data_prefix):

        """Set up paths for running from a regular installation."""

        pass

    @classmethod
    def setup_uninstalled (cls, source_dir):

        """Set up paths for running 'uninstalled' (i.e. directly from the
        source dist)."""

        pass

    @classmethod
    def ensure_setup (cls):

        """If paths are still not set up, try to set from a fallback."""

        if cls.data_dir is None:
            source_dir = os.path.dirname (os.path.dirname (os.path.abspath (__file__)))
            cls.setup_uninstalled (source_dir)

    def __new__ (cls):

        raise RuntimeError ("do not create instances of this class -- "
                            "use the class object directly")

class PathsProgramBase (PathsBase):

    program_name = None

    @classmethod
    def setup_installed (cls, data_prefix):

        if cls.program_name is None:
            raise NotImplementedError ("derived classes need to set program_name attribute")

        cls.data_dir = os.path.join (data_prefix, "share", cls.program_name)
        cls.icon_dir = os.path.join (data_prefix, "share", "icons")
        cls.locale_dir = os.path.join (data_prefix, "share", "locale")

    @classmethod
    def setup_uninstalled (cls, source_dir):

        """Set up paths for running 'uninstalled' (i.e. directly from the
        source dist)."""

        # This is essential: The GUI module needs to find the .glade file.
        cls.data_dir = os.path.join (source_dir, "data")

        # The locale data might be missing if "setup.py build" wasn't run.
        cls.locale_dir = os.path.join (source_dir, "build", "mo")

        # Not setting icon_dir.  It is not useful since we don't employ the
        # needed directory structure in the source dist.

class OptionError (Exception):

    pass

class OptionParser (object):

    def __init__ (self, options):

        self.__entries = []
        self.__parsers = {}

        self.options = options

        self.__remaining_args = []

        # Remaining args parsing with pygobject does not work with glib before
        # 2.13.2 (e.g. Ubuntu Feisty).
        ## if gobject.glib_version >= (2, 13, 2,):
        ##     self.__entries.append ((gobject.OPTION_REMAINING, "\0", 0, "", "",))

    def add_option (self, long_name, short_name = None, description = None,
                    arg_name = None, arg_parser = None, hidden = False):

        flags = 0

        if not short_name:
            # A deficiency of pygobject:
            short_name = "\0"

        if not description:
            description = ""

        if arg_name is None:
            flags |= gobject.OPTION_FLAG_NO_ARG
        elif arg_parser is not None:
            self.__parsers[long_name] = arg_parser

        if hidden:
            flags |= gobject.OPTION_FLAG_HIDDEN

        self.__entries.append ((long_name, short_name, flags, description,
                                arg_name,))

    def __handle_option (self, option, arg, group):

        # See __init__ for glib requirement.
        ## if option == gobject.OPTION_REMAINING:
        ##     self.__remaining_args.append (arg)
        ##     return

        for entry in self.__entries:
            long_name, short_name = entry[:2]
            arg_name = entry[-1]
            if (option != "--%s" % (long_name,) and
                option != "-%s" % (short_name,)):
                continue
            attr = long_name.replace ("-", "_")
            if arg_name is None:
                value = True
            elif long_name in self.__parsers:
                value = self.__parsers[long_name](arg)
            else:
                value = arg
            self.options[attr] = value
            break

    def parse (self, argv):

        context = gobject.OptionContext (self.get_parameter_string ())
        group = gobject.OptionGroup (None, None, None, self.__handle_option)
        context.set_main_group (group)
        group.add_entries (self.__entries)

        try:
            result_argv = context.parse (argv)
        except gobject.GError as exc:
            raise OptionError (exc.message)

        self.__remaining_args = result_argv[1:]

        self.handle_parse_complete (self.__remaining_args)

    def get_parameter_string (self):

        raise NotImplementedError ("derived classes must override this method")

    def handle_parse_complete (self, remaining_args):

        pass

class LogOptionParser (OptionParser):

    """Like OptionParser, but adds a --log-level option."""

    def __init__ (self, *a, **kw):

        OptionParser.__init__ (self, *a, **kw)

        # TODO: Re-evaluate usage of log levels to use less of them.  Like
        # unifying warning, error and critical.

        self.add_option ("log-level", "l",
                         "%s (debug, info, warning, error, critical)"
                         % (_("Enable logging"),),
                         "LEVEL", self.parse_log_level)

    @staticmethod
    def parse_log_level (arg):

        try:
            level = int (arg)
        except ValueError:
            level = {"off" : None,
                     "none" : None,
                     "debug" : logging.DEBUG,
                     "info" : logging.INFO,
                     "warning" : logging.WARNING,
                     "error" : logging.ERROR,
                     "critical" : logging.CRITICAL}.get (arg.strip ().lower ())
            if level is None:
                return None
            else:
                return level
        else:
            if level < 0:
                level = 0
            elif level > 5:
                level = 5
            return {0 : None,
                    1 : logging.DEBUG,
                    2 : logging.INFO,
                    3 : logging.WARNING,
                    4 : logging.ERROR,
                    5 : logging.CRITICAL}[level]

def _init_excepthooks ():

    ExceptHookManager.setup ()
    ExceptHookManager.register_handler (ExitOnInterruptExceptionHandler ())

def _init_paths (paths):

    paths.ensure_setup ()

def _init_locale (gettext_domain = None):

    if Paths.locale_dir and gettext_domain is not None:
        try:
            locale.setlocale (locale.LC_ALL, "")
        except locale.Error as exc:
            from warnings import warn
            warn ("locale error: %s" % (exc,),
                  RuntimeWarning,
                  stacklevel = 2)
            Paths.locale_dir = None
        else:
            gettext.bindtextdomain (gettext_domain, Paths.locale_dir)
            gettext.textdomain (gettext_domain)
            gettext.bind_textdomain_codeset (gettext_domain, "UTF-8")

def _init_options (option_parser = None):

    if option_parser is None:
        return {}

    try:
        option_parser.parse (sys.argv)
    except OptionError as exc:
        print >> sys.stderr, exc.args[0]
        sys.exit (1)

    return option_parser.options

def _init_logging (level = None):

    logging.basicConfig (level = level,
                         format = '%(asctime)s.%(msecs)03d %(levelname)8s %(name)20s: %(message)s',
                         datefmt = '%H:%M:%S')

    logger = logging.getLogger ("main")
    logger.debug ("logging at level %s", logging.getLevelName (level))
    logger.info ("using Python %i.%i.%i %s %i", *sys.version_info)

def main (option_parser = None, gettext_domain = None, paths = None):

    # FIXME:
    global Paths
    Paths = paths

    _init_excepthooks ()
    _init_paths (paths)
    _init_locale (gettext_domain)
    options = _init_options (option_parser)
    try:
        log_level = options["log_level"]
    except KeyError:
        _init_logging ()
    else:
        _init_logging (log_level)

    try:
        options["main"] (options)
    finally:
        logging.shutdown ()
