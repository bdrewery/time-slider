#!/usr/bin/env python
#
# CDDL HEADER START
#
# The contents of this file are subject to the terms of the
# Common Development and Distribution License (the "License").
# You may not use this file except in compliance with the License.
#
# You can obtain a copy of the license at usr/src/OPENSOLARIS.LICENSE
# or http://www.opensolaris.org/os/licensing.
# See the License for the specific language governing permissions
# and limitations under the License.
#
# When distributing Covered Code, include this CDDL HEADER in each
# file and include the License file at usr/src/OPENSOLARIS.LICENSE.
# If applicable, add the following below this CDDL HEADER, with the
# fields enclosed by brackets "[]" replaced with your own identifying
# information: Portions Copyright [yyyy] [name of copyright owner]
#
# CDDL HEADER END
#

import threading
import sys
import os
import time
import getopt

try:
    import pygtk
    pygtk.require("2.4")
except:
    pass
try:
    import gtk
    import gtk.glade
    gtk.gdk.threads_init()
except:
    sys.exit(1)
try:
    import glib
    import gobject
except:
    sys.exit(1)

# here we define the path constants so that other modules can use it.
# this allows us to get access to the shared files without having to
# know the actual location, we just use the location of the current
# file and use paths relative to that.
SHARED_FILES = os.path.abspath(os.path.join(os.path.dirname(__file__),
                               os.path.pardir,
                               os.path.pardir))
LOCALE_PATH = os.path.join('/usr', 'share', 'locale')
RESOURCE_PATH = os.path.join(SHARED_FILES, 'res')

# the name of the gettext domain. because we have our translation files
# not in a global folder this doesn't really matter, setting it to the
# application name is a good idea tough.
GETTEXT_DOMAIN = 'time-slider'

# set up the glade gettext system and locales
gtk.glade.bindtextdomain(GETTEXT_DOMAIN, LOCALE_PATH)
gtk.glade.textdomain(GETTEXT_DOMAIN)

import zfs
from smfmanager import SMFManager
from rbac import RBACprofile

class DeleteSnapManager:

    def __init__(self, snapshots = None):
        self.xml = gtk.glade.XML("%s/../../glade/time-slider-delete.glade" \
                                  % (os.path.dirname(__file__)))
        self.snapstodelete = []
        self.shortcircuit = []
        maindialog = self.xml.get_widget("time-slider-delete")
        self.pulsedialog = self.xml.get_widget("pulsedialog")
        self.pulsedialog.set_transient_for(maindialog)
        if snapshots:
            maindialog.hide()
            self.shortcircuit = snapshots
        else:
            glib.idle_add(self.__init_scan)

        self.progressdialog = self.xml.get_widget("deletingdialog")
        self.progressdialog.set_transient_for(maindialog)
        self.progressbar = self.xml.get_widget("deletingprogress")
        # signal dictionary	
        dic = {"on_closebutton_clicked" : gtk.main_quit,
               "on_window_delete_event" : gtk.main_quit,
               "on_snapshotmanager_delete_event" : gtk.main_quit,
               "on_fsfilterentry_changed" : self.__on_filterentry_changed,
               "on_schedfilterentry_changed" : self.__on_filterentry_changed,
               "on_selectbutton_clicked" : self.__on_selectbutton_clicked,
               "on_deselectbutton_clicked" : self.__on_deselectbutton_clicked,
               "on_deletebutton_clicked" : self.__on_deletebutton_clicked,
               "on_confirmcancel_clicked" : self.__on_confirmcancel_clicked,
               "on_confirmdelete_clicked" : self.__on_confirmdelete_clicked,
               "on_errordialog_response" : self.__on_errordialog_response}
        self.xml.signal_autoconnect(dic)

    def __create_snapshot_list_store(self):

        for snapshot in self.snapscanner.snapshots:
            try:
                self.liststorefs.append([
                       self.snapscanner.mounts[snapshot.fsname],
                       snapshot.fsname,
                       snapshot.snaplabel,
                       time.ctime(snapshot.get_creation_time()),
                       snapshot.get_creation_time(),
                       snapshot])
            except KeyError:
                continue
                # This will catch exceptions from things we ignore
                # such as dump and swap volumes and skip over them.

    def initialise_view(self):
        if len(self.shortcircuit) == 0:
            # Set TreeViews
            self.liststorefs = gtk.ListStore(str, str, str, str, long,
                                             gobject.TYPE_PYOBJECT)
            list_filter = self.liststorefs.filter_new()
            list_sort = gtk.TreeModelSort(list_filter)
            list_sort.set_sort_column_id(1, gtk.SORT_ASCENDING)

            self.snaptreeview = self.xml.get_widget("snaplist")
            self.snaptreeview.set_model(self.liststorefs)
            self.snaptreeview.get_selection().set_mode(gtk.SELECTION_MULTIPLE)

            cell0 = gtk.CellRendererText()
            cell1 = gtk.CellRendererText()
            cell2 = gtk.CellRendererText()
            cell3 = gtk.CellRendererText()

            mountptcol = gtk.TreeViewColumn(_("Mount Point"),
                                            cell0, text = 0)
            mountptcol.set_sort_column_id(0)
            mountptcol.set_resizable(True)
            mountptcol.connect("clicked",
                self.__on_treeviewcol_clicked, 0)
            self.snaptreeview.append_column(mountptcol)

            fsnamecol = gtk.TreeViewColumn(_("File System Name"),
                                           cell1, text = 1)
            fsnamecol.set_sort_column_id(1)
            fsnamecol.set_resizable(True)
            fsnamecol.connect("clicked",
                self.__on_treeviewcol_clicked, 1)
            self.snaptreeview.append_column(fsnamecol)

            snaplabelcol = gtk.TreeViewColumn(_("Snapshot Name"),
                                              cell2, text = 2)
            snaplabelcol.set_sort_column_id(2)
            snaplabelcol.set_resizable(True)
            snaplabelcol.connect("clicked",
                self.__on_treeviewcol_clicked, 2)
            self.snaptreeview.append_column(snaplabelcol)

            creationcol = gtk.TreeViewColumn(_("Creation Time"),
                                             cell3, text = 3)
            creationcol.set_sort_column_id(4)
            creationcol.set_resizable(True)
            creationcol.connect("clicked",
                self.__on_treeviewcol_clicked, 3)
            self.snaptreeview.append_column(creationcol)


            # Note to translators
            # The second element is for internal matching and should not
            # be translated under any circumstances.        
            fsstore = gtk.ListStore(str, str)
            fslist = zfs.list_filesystems()
            fsstore.append([_("All"), None])
            for fsname in fslist:
                fsstore.append([fsname, fsname])
            self.fsfilterentry = self.xml.get_widget("fsfilterentry")
            self.fsfilterentry.set_model(fsstore)
            self.fsfilterentry.set_text_column(0)
            fsfilterentryCell = gtk.CellRendererText()
            self.fsfilterentry.pack_start(fsfilterentryCell)

            schedstore = gtk.ListStore(str, str)
            # Note to translators
            # The second element is for internal matching and should not
            # be translated under any circumstances.
            schedstore.append([_("All"), None])
            schedstore.append([_("Monthly"), "zfs-auto-snap:monthly"])
            schedstore.append([_("Weekly"), "zfs-auto-snap:weekly"])
            schedstore.append([_("Daily"), "zfs-auto-snap:daily"])
            schedstore.append([_("Hourly"), "zfs-auto-snap:hourly"])
            schedstore.append([_("1/4 Hourly"), "zfs-auto-snap:frequent"])
            self.schedfilterentry = self.xml.get_widget("schedfilterentry")
            self.schedfilterentry.set_model(schedstore)
            self.schedfilterentry.set_text_column(0)
            schedentryCell = gtk.CellRendererText()
            self.schedfilterentry.pack_start(schedentryCell)

            self.schedfilterentry.set_active(0)
            self.fsfilterentry.set_active(0)
        else:
            cloned = zfs.list_cloned_snapshots()
            for snapname in self.shortcircuit:
                # Filter out snapshots that are the root 
                # of cloned filesystems or volumes
                try:
                    cloned.index(snapname)
                    dialog = gtk.MessageDialog(None,
                                   0,
                                   gtk.MESSAGE_ERROR,
                                   gtk.BUTTONS_CLOSE,
                                   _("Snapshot can not be deleted"))
                    text = _("%s has one or more dependent clones "
                             "and will not be deleted. To delete "
                             "this snapshot, first delete all "
                             "datasets and snapshots cloned from "
                             "this snapshot.") \
                             % snapname
                    dialog.format_secondary_text(text)
                    dialog.run()
                    sys.exit(1)
                except ValueError:
                    snapshot = zfs.Snapshot(snapname)
                    self.snapstodelete.append(snapshot)
            confirm = self.xml.get_widget("confirmdialog")
            summary = self.xml.get_widget("summarylabel")
            total = len(self.snapstodelete)
            if total == 1:
                summary.set_text(_("1 snapshot will be deleted."))
            else:
                summary.set_text(_("%d snapshots will be deleted.") \
                                 % total)
            response = confirm.run()
            if response != 2:
                sys.exit(0)
            else:
                # Create the thread in an idle loop in order to
                # avoid deadlock inside gtk.
                glib.idle_add(self.__init_delete)
        return False

    def __on_treeviewcol_clicked(self, widget, searchcol):
        self.snaptreeview.set_search_column(searchcol)

    def __filter_snapshot_list(self, list, filesys = None, snap = None):
        if filesys == None and snap == None:
            return list
        fssublist = []
        if filesys != None:
            for snapshot in list:
                if snapshot.fsname.find(filesys) != -1:
                    fssublist.append(snapshot)
        else:
            fssublist = list

        snaplist = []
        if snap != None:
            for snapshot in fssublist:
                if  snapshot.snaplabel.find(snap) != -1:
                    snaplist.append(snapshot)
        else:
            snaplist = fssublist
        return snaplist

    def __on_filterentry_changed(self, widget):
        # Get the filesystem filter value
        iter = self.fsfilterentry.get_active_iter()
        if iter == None:
            filesys = self.fsfilterentry.get_active_text()
        else:
            model = self.fsfilterentry.get_model()
            filesys = model.get(iter, 1)[0]
        # Get the snapshot name filter value
        iter = self.schedfilterentry.get_active_iter()
        if iter == None:
            snap = self.schedfilterentry.get_active_text()
        else:
            model = self.schedfilterentry.get_model()
            snap = model.get(iter, 1)[0]

        self.liststorefs.clear()
        newlist = self.__filter_snapshot_list(self.snapscanner.snapshots,
                    filesys,
                    snap)
        for snapshot in newlist:
            try:
                self.liststorefs.append([
                       self.snapscanner.mounts[snapshot.fsname],
                       snapshot.fsname,
                       snapshot.snaplabel,
                       time.ctime(snapshot.get_creation_time()),
                       snapshot.get_creation_time(),
                       snapshot])
            except KeyError:
                continue
                # This will catch exceptions from things we ignore
                # such as dump as swap volumes and skip over them.

    def __on_selectbutton_clicked(self, widget):
        selection = self.snaptreeview.get_selection()
        selection.select_all()
        return

    def __on_deselectbutton_clicked(self, widget):
        selection = self.snaptreeview.get_selection()
        selection.unselect_all()
        return

    def __on_deletebutton_clicked(self, widget):
        self.snapstodelete = []
        selection = self.snaptreeview.get_selection()
        selection.selected_foreach(self.__add_selection)
        total = len(self.snapstodelete)
        if total <= 0:
            return

        confirm = self.xml.get_widget("confirmdialog")
        summary = self.xml.get_widget("summarylabel")
        if total == 1:
            summary.set_text(_("1 snapshot will be deleted."))
        else:
            summary.set_text(_("%d snapshots will be deleted.") \
                       % total)
        response = confirm.run()
        if response != 2:
            return
        else:
            glib.idle_add(self.__init_delete)
        return
        
    def __init_scan(self):
        self.snapscanner = ScanSnapshots()
        self.pulsedialog.show()
        self.snapscanner.start()
        glib.timeout_add(100, self.__monitor_scan)  
        return False

    def __init_delete(self):
        self.snapdeleter = DeleteSnapshots(self.snapstodelete)
        # If there's more than a few snapshots, pop up
        # a progress bar.
        if len(self.snapstodelete) > 3:
            self.progressbar.set_fraction(0.0)
            self.progressdialog.show()        
        self.snapdeleter.start()
        glib.timeout_add(300, self.__monitor_deletion)  
        return False

    def __monitor_scan(self):
        if self.snapscanner.isAlive() == True:
            self.xml.get_widget("pulsebar").pulse()
            return True
        else:
            self.pulsedialog.hide()
            if self.snapscanner.errors:
                details = ""
                dialog = gtk.MessageDialog(None,
                            0,
                            gtk.MESSAGE_ERROR,
                            gtk.BUTTONS_CLOSE,
                            _("Some snapshots could not be read"))
                dialog.connect("response",
                            self.on_errordialog_response)                 
                for error in self.snapscanner.errors:
                    details = details + error
                dialog.format_secondary_text(details)
                dialog.show()
            self.__on_filterentry_changed(None)
            return False

    def __monitor_deletion(self):
        if self.snapdeleter.isAlive() == True:
            self.progressbar.set_fraction(self.snapdeleter.progress)
            return True
        else:
            self.progressdialog.hide()
            self.progressbar.set_fraction(1.0)
            self.progressdialog.hide()
            if self.snapdeleter.errors:
                details = ""
                dialog = gtk.MessageDialog(None,
                            0,
                            gtk.MESSAGE_ERROR,
                            gtk.BUTTONS_CLOSE,
                            _("Some snapshots could not be deleted"))
                dialog.connect("response",
                            self.on_errordialog_response)                 
                for error in self.snapdeleter.errors:
                    details = details + error
                dialog.format_secondary_text(details)
                dialog.show()
            # If we didn't shortcircut straight to the delete confirmation
            # dialog then the main dialog is visible so we rebuild the list
            # view.
            if len(self.shortcircuit) ==  0:
                self.__refresh_view()
            else:
                gtk.main_quit()
            return False

    def __refresh_view(self):
        self.liststorefs.clear()
        glib.idle_add(self.__init_scan)        
        self.snapstodelete = []

    def __add_selection(self, treemodel, path, iter):
        snapshot = treemodel.get(iter, 5)[0]
        self.snapstodelete.append(snapshot)

    def __on_confirmcancel_clicked(self, widget):
        widget.get_toplevel().hide()
        widget.get_toplevel().response(1)

    def __on_confirmdelete_clicked(self, widget):
        widget.get_toplevel().hide()
        widget.get_toplevel().response(2)

    def __on_errordialog_response(self, widget, responseid):
        widget.hide()

class ScanSnapshots(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.errors = []
        self.snapshots = []

    def run(self):
        self.mounts = self.__get_fs_mountpoints()
        self.rescan()

    def __get_fs_mountpoints(self):
        """Returns a dictionary mapping: 
           {filesystem : mountpoint}"""
        cmd = "zfs list -H -t filesystem -o name,mountpoint"
        fin,fout,ferr = os.popen3(cmd)
        result = {}
        for line in fout:
            line = line.rstrip().split()
            result[line[0]] = line[1]
        return result

    def rescan(self):
        cloned = zfs.list_cloned_snapshots()
        self.snapshots = []
        snaplist = zfs.list_snapshots()
        for snapname,snaptime in snaplist:  
            # Filter out snapshots that are the root 
            # of cloned filesystems or volumes
            try:
                cloned.index(snapname)
            except ValueError:
                snapshot = zfs.Snapshot(snapname, snaptime)
                self.snapshots.append(snapshot)

class DeleteSnapshots(threading.Thread):

    def __init__(self, snapshots):
        threading.Thread.__init__(self)
        self.snapstodelete = snapshots
        self.started = False
        self.completed = False
        self.progress = 0.0
        self.errors = []

    def run(self):
        deleted = 0
        self.started = True
        total = len(self.snapstodelete)
        for snapshot in self.snapstodelete:
            # The snapshot could have expired and been automatically
            # destroyed since the user selected it. Check that it
            # still exists before attempting to delete it. If it 
            # doesn't exist just silently ignore it.
            if snapshot.exists():
                error = snapshot.destroy_snapshot()
                if error:
                    self.errors.append(error)
            deleted += 1
            self.progress = deleted / (total * 1.0)
        self.completed = True

def main(argv):
    try:
        opts,args = getopt.getopt(sys.argv[1:], "", [])
    except getopt.GetoptError:
        sys.exit(2)
    rbacp = RBACprofile()
    # The user security attributes checked are the following:
    # 1. The "Primary Administrator" role
    # 4. The "ZFS Files System Management" profile.
    #
    # Valid combinations of the above are:
    # - 1 or 4
    # Note that an effective UID=0 will match any profile search so
    # no need to check it explicitly.
    if rbacp.has_profile("Primary Administrator") or \
            rbacp.has_profile("ZFS File System Management"):
        if len(args) > 0:
            manager = DeleteSnapManager(args)
        else:
            manager = DeleteSnapManager()
        gtk.gdk.threads_enter()
        glib.idle_add(manager.initialise_view)
        gtk.main()
        gtk.gdk.threads_leave()
    elif os.path.exists(argv) and os.path.exists("/usr/bin/gksu"):
        # Run via gksu, which will prompt for the root password
        newargs = ["gksu", argv]
        for arg in args:
            newargs.append(arg)
        os.execv("/usr/bin/gksu", newargs);
        # Shouldn't reach this point
        sys.exit(1)
    else:
        dialog = gtk.MessageDialog(None,
                                   0,
                                   gtk.MESSAGE_ERROR,
                                   gtk.BUTTONS_CLOSE,
                                   _("Insufficient Priviliges"))
        dialog.format_secondary_text(_("Snapshot deletion requires "
                                       "administrative privileges to run. "
                                       "You have not been assigned the necessary"
                                       "administrative priviliges."
                                       "\n\nConsult your system administrator "))
        dialog.run()
        print argv + "is not a valid executable path"
        sys.exit(1)

