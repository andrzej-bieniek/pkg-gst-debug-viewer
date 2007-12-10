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

"""GStreamer Debug Viewer timeline widget plugin."""

import logging

from GstDebugViewer import Common, Data, GUI
from GstDebugViewer.Plugins import *

import pango
import gtk

class SearchOperation (object):

    def __init__ (self, model, search_string, search_forward = True, start_position = None):

        self.model = model
        self.search_string = search_string
        self.search_forward = search_forward
        self.start_position = start_position

        col_id = GUI.LogModelBase.COL_MESSAGE
        len_search_string = len (search_string)
        
        def match_func (model_row):

            message = model_row[col_id]
            if search_string in message:
                # TODO: Return all match ranges here.
                pos = message.find (search_string)
                return ((pos, pos + len_search_string,),)
            else:
                return ()

        self.match_func = match_func

class SearchSentinel (object):

    def __init__ (self):

        self.dispatcher = Common.Data.GSourceDispatcher ()
        self.cancelled = False

    def run_for (self, operation):

        self.dispatcher.cancel ()
        self.dispatcher (self.__process (operation))
        self.cancelled = False

    def abort (self):

        self.dispatcher.cancel ()
        self.cancelled = True

    def __process (self, operation):

        model = operation.model

        if operation.start_position is not None:
            start_iter = model.iter_nth_child (None, operation.start_position)
        else:
            start_iter = model.iter_nth_child (None, 0)

        if not operation.search_forward:
            # FIXME:
            raise NotImplementedError ("backward search not supported yet")

        match_func = operation.match_func
        iter_next = model.iter_next

        YIELD_LIMIT = 1000
        i = YIELD_LIMIT
        tree_iter = start_iter
        while tree_iter and not self.cancelled:
            i -= 1
            if i == 0:
                yield True
                i = YIELD_LIMIT
            row = model[tree_iter]
            if match_func (row):
                self.handle_match_found (model, tree_iter)
            tree_iter = iter_next (tree_iter)

        if not self.cancelled:
            self.handle_search_complete ()
        yield False

    def handle_match_found (self, model, tree_iter):

        pass

    def handle_search_complete (self):

        pass

class FindBarWidget (gtk.HBox):

    __status = {"no-match-found" : _N("No match found"),
                "searching" : _N("Searching...")}

    def __init__ (self, action_group):

        gtk.HBox.__init__ (self)

        label = gtk.Label (_("Find:"))
        self.pack_start (label, False, False, 2)

        self.entry = gtk.Entry ()
        self.pack_start (self.entry)

        prev_action = action_group.get_action ("goto-previous-search-result")
        prev_button = gtk.Button ()
        prev_action.connect_proxy (prev_button)
        self.pack_start (prev_button, False, False, 0)

        next_action = action_group.get_action ("goto-next-search-result")
        next_button = gtk.Button ()
        next_action.connect_proxy (next_button)
        self.pack_start (next_button, False, False, 0)

        self.status_label = gtk.Label ("")
        self.status_label.props.xalign = 0.
        attrs = pango.AttrList ()
        attrs.insert (pango.AttrWeight (pango.WEIGHT_BOLD, 0, -1))
        self.status_label.props.attributes = attrs
        self.pack_start (self.status_label, False, False, 6)
        self.__compute_status_size ()
        self.status_label.connect ("notify::style", self.__handle_notify_style)

        self.show_all ()

    def __compute_status_size (self):

        label = self.status_label
        old_text = label.props.label
        label.set_size_request (-1, -1)
        max_width = 0
        try:
            for status in self.__status.values ():
                self.__set_status (_(status))
                width, height = label.size_request ()
                max_width = max (max_width, width)
            label.set_size_request (max_width, -1)
        finally:
            label.props.label = old_text

    def __handle_notify_style (self, *a, **kw):

        self.__compute_status_size ()

    def __set_status (self, text):

        self.status_label.props.label = text

    def status_no_match_found (self):

        self.__set_status (_(self.__status["no-match-found"]))

    def status_searching (self):

        self.__set_status (_(self.__status["searching"]))

    def clear_status (self):

        self.__set_status ("")

class FindBarFeature (FeatureBase):

    def __init__ (self, app):

        FeatureBase.__init__ (self, app)

        self.matches = []

        self.logger = logging.getLogger ("ui.findbar")

        self.action_group = gtk.ActionGroup ("FindBarActions")
        self.action_group.add_toggle_actions ([("show-find-bar",
                                                None,
                                                _("Find Bar"),
                                                "<Ctrl>F")])
        self.action_group.add_actions ([("goto-next-search-result",
                                         None, _("Goto Next Match"),
                                         None), # FIXME
                                        ("goto-previous-search-result",
                                         None, _("Goto Previous Match"),
                                         None)]) # FIXME

        self.bar = None
        self.operation = None
        self.search_state = None
        self.next_match = None
        self.prev_match = None
        self.scroll_match = False

        self.sentinel = SearchSentinel ()
        self.sentinel.handle_match_found = self.handle_match_found
        self.sentinel.handle_search_complete = self.handle_search_complete

    def scroll_view_to_line (self, line_index):

        view = self.log_view

        path = (line_index,)

        start_path, end_path = view.get_visible_range ()

        if path >= start_path and path <= end_path:
            self.logger.debug ("line index %i already visible, not scrolling", line_index)
            return

        self.logger.debug ("scrolling to line_index %i", line_index)
        view.scroll_to_cell (path, use_align = True, row_align = .5)

    def handle_attach_window (self, window):

        self.window = window

        ui = window.ui_manager

        ui.insert_action_group (self.action_group, 0)

        self.log_view = window.log_view
        
        self.merge_id = ui.new_merge_id ()
        ui.add_ui (self.merge_id, "/menubar/ViewMenu/ViewMenuAdditions",
                   "ViewFindBar", "show-find-bar",
                   gtk.UI_MANAGER_MENUITEM, False)

        box = window.widgets.vbox_view
        self.bar = FindBarWidget (self.action_group)
        box.pack_end (self.bar, False, False, 0)
        self.bar.hide ()

        action = self.action_group.get_action ("show-find-bar")
        handler = self.handle_show_find_bar_action_toggled
        action.connect ("toggled", handler)

        action = self.action_group.get_action ("goto-previous-search-result")
        handler = self.handle_goto_previous_search_result_action_activate
        action.connect ("activate", handler)

        action = self.action_group.get_action ("goto-next-search-result")
        handler = self.handle_goto_next_search_result_action_activate
        action.connect ("activate", handler)

        self.bar.entry.connect ("changed", self.handle_entry_changed)

    def handle_detach_window (self, window):

        self.window = None

        window.ui_manager.remove_ui (self.merge_id)
        self.merge_id = None

    def handle_show_find_bar_action_toggled (self, action):

        if action.props.active:
            self.bar.show ()
            self.bar.entry.grab_focus ()
        else:
            try:
                column = self.window.column_manager.find_item (name = "message")
                del column.highlighters[self]
            except KeyError:
                pass
            self.bar.clear_status ()
            self.bar.hide ()

    def handle_goto_previous_search_result_action_activate (self, action):

        model = self.log_view.props.model

        start_path, end_path = self.log_view.get_visible_range ()
        start_index, end_index = start_path[0], end_path[0]

        for line_index in reversed (self.matches):
            if line_index < start_index:
                break
        else:
            return

        self.scroll_view_to_line (line_index)

    def handle_goto_next_search_result_action_activate (self, action):

        if self.next_match is None:
            self.logger.warning ("inconsistent action sensitivity")
            return

        self.scroll_view_to_line (self.next_match)
        self.next_match = None

        end_path = self.log_view.get_visible_range ()[1]
        new_position = end_path[0] + 1
        self.start_search_operation (start_position = new_position)
        # FIXME: Finish.

        ## model = self.log_view.props.model

        ## start_path, end_path = self.log_view.get_visible_range ()
        ## start_index, end_index = start_path[0], end_path[0]

        ## for line_index in self.matches:
        ##     if line_index > end_index:
        ##         break
        ## else:
        ##     return

        ## self.scroll_view_to_line (line_index)

    def handle_entry_changed (self, entry):

        self.clear_results ()

        model = self.log_view.props.model
        search_string = entry.props.text
        column = self.window.column_manager.find_item (name = "message")
        if search_string == "":
            self.logger.debug ("search string set to '', aborting search")
            self.search_state = None
            self.next_match = None
            self.prev_match = None
            self.update_sensitivity ()
            self.sentinel.abort ()
            self.clear_results ()
            try:
                del column.highlighters[self]
            except KeyError:
                pass
        else:
            self.logger.debug ("starting search for %r", search_string)
            self.next_match = None
            self.prev_match = None
            self.update_sensitivity ()
            self.scroll_match = True

            start_path = self.log_view.get_visible_range ()[0]
            self.start_search_operation (search_string, start_position = start_path[0])
            self.bar.status_searching ()
            column.highlighters[self] = self.operation.match_func

        self.window.update_view ()

    def update_sensitivity (self):

        for name, value in (("goto-next-search-result", self.next_match,),
                            ("goto-previous-search-result", self.prev_match,),):
            action = self.action_group.get_action (name)
            action.props.sensitive = (value is not None)

    def start_search_operation (self, search_string = None, forward = True, start_position = None):

        model = self.log_view.props.model

        if forward:
            self.search_state = "search-forward"
            if start_position is None:
                start_position = 0
        else:
            self.search_state = "search-backward"
            if start_position is None:
                start_position = len (model) - 1

        if search_string is None:
            operation = self.operation
            if operation is None:
                raise ValueError ("search_string not given but have no previous search operation")
            search_string = operation.search_string

        self.operation = SearchOperation (model, search_string, start_position = start_position)
        self.sentinel.run_for (self.operation)

    def handle_match_found (self, model, tree_iter):

        if not self.search_state in ("search-forward", "search-backward",):
            self.logger.warning ("inconsistent search state %r", self.search_state)
            return

        line_index = model.get_path (tree_iter)[0]
        forward_search = (self.search_state == "search-forward")

        if forward_search:
            self.logger.debug ("forward search for %r matches line %i",
                               self.operation.search_string, line_index)
        else:
            self.logger.debug ("backward search for %r matches line %i",
                               self.operation.search_string, line_index)

        self.sentinel.abort ()

        if self.scroll_match:
            self.logger.debug ("scrolling to matching line")
            self.scroll_view_to_line (line_index)
            # FIXME: Implement backward search!!!

            # Now search for the next one:
            self.scroll_match = False
            self.start_search_operation (start_position = line_index + 1)
        else:
            if forward_search:
                self.next_match = line_index
            else:
                self.prev_match = line_index
            self.update_sensitivity ()
            self.bar.clear_status ()

    def handle_search_complete (self):

        if self.search_state == "search-forward":
            self.logger.debug ("forward search for %r reached last line",
                               self.operation.search_string)
            self.next_match = None
        elif self.search_state == "search-backward":
            self.logger.debug ("backward search for %r reached first line",
                               self.operation.search_string)
            self.prev_match = None
        else:
            self.logger.warning ("inconsistent search state %r",
                                 self.search_state)
            return

        self.update_sensitivity ()
        if self.prev_match is None and self.next_match is None:
            self.bar.status_no_match_found ()

    def update_results (self, finished = False):

        INTERVAL = 100

        if finished and len (self.matches) == 0:
            self.bar.status_no_match_found ()
        elif finished:
            self.bar.clear_status ()

        if len (self.matches) % INTERVAL == 0:
            new_matches = self.matches[-INTERVAL:]
        elif finished:
            new_matches = self.matches[-(len (self.matches) % INTERVAL):]
        else:
            return

    def clear_results (self):

        try:
            column = self.window.column_manager.find_item (name = "message")
            del column.highlighters[self]
        except KeyError:
            pass

        model = self.log_view.props.model

        start_path, end_path = self.log_view.get_visible_range ()
        start_index, end_index = start_path[0], end_path[0]

        for line_index in range (start_index, end_index + 1):
            if line_index in self.matches:
                tree_path = (line_index,)
                tree_iter = model.get_iter (tree_path)
                model.row_changed (tree_path, tree_iter)

        del self.matches[:]

        self.bar.clear_status ()

class Plugin (PluginBase):

    features = [FindBarFeature]
