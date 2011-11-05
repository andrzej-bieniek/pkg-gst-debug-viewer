# -*- coding: utf-8; mode: python; -*-
#
#  GStreamer Debug Viewer - View and analyze GStreamer debug log files
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

"""GStreamer Debug Viewer GUI module."""

import os.path

import gobject
import gtk

from GstDebugViewer import Common
from GstDebugViewer.GUI.columns import ViewColumnManager
from GstDebugViewer.GUI.window import Window

class AppStateSection (Common.GUI.StateSection):

    _name = "state"

    geometry = Common.GUI.StateInt4 ("window-geometry")
    maximized = Common.GUI.StateBool ("window-maximized")

    column_order = Common.GUI.StateItemList ("column-order", ViewColumnManager)
    columns_visible = Common.GUI.StateItemList ("columns-visible", ViewColumnManager)

    zoom_level = Common.GUI.StateInt ("zoom-level")

class AppState (Common.GUI.State):

    def __init__ (self, *a, **kw):

        Common.GUI.State.__init__ (self, *a, **kw)

        self.add_section_class (AppStateSection)

class App (object):

    def __init__ (self):

        self.attach ()

    def load_plugins (self):

        from GstDebugViewer import Plugins

        plugin_classes = list (Plugins.load ([os.path.dirname (Plugins.__file__)]))
        self.plugins = []
        for plugin_class in plugin_classes:
            plugin = plugin_class (self)
            self.plugins.append (plugin)

    def iter_plugin_features (self):

        for plugin in self.plugins:
            for feature in plugin.features:
                yield feature

    def attach (self):

        config_home = Common.utils.XDG.CONFIG_HOME

        state_filename = os.path.join (config_home, "gst-debug-viewer", "state")

        self.state = AppState (state_filename)
        self.state_section = self.state.sections["state"]

        self.load_plugins ()

        self.windows = []
        
        # we override expander size because of:
        # https://bugzilla.gnome.org/show_bug.cgi?id=615985
        rcstring = """
        style "no-expander-treeview-style" {
            GtkTreeView::expander_size = 1
            #GtkTreeView::vertical-separator = 0
            GtkWidget::focus-line-width = 0
        }
        
        widget "*.log_view" style "no-expander-treeview-style"
        """
        gtk.rc_parse_string (rcstring)

        self.open_window ()

    def detach (self):

        # TODO: If we take over deferred saving from the inspector, specify now
        # = True here!
        self.state.save ()

    def run (self):

        try:
            Common.Main.MainLoopWrapper (gtk.main, gtk.main_quit).run ()
        except:
            raise
        else:
            self.detach ()

    def open_window (self):

        self.windows.append (Window (self))

    def close_window (self, window):

        self.windows.remove (window)
        if not self.windows:
            # GtkTreeView takes some time to go down for large files.  Let's block
            # until the window is hidden:
            gobject.idle_add (gtk.main_quit)
            gtk.main ()

            gtk.main_quit ()
