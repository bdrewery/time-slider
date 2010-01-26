#!/usr/bin/python2.6
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

import sys
import os
import subprocess
import threading
from autosnapsmf import enable_default_schedules, disable_default_schedules

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

class FilesystemIntention:

    def __init__(self, name, selected, inherited):
        self.name = name
        self.selected = selected
        self.inherited = inherited

class SetupManager:

    def __init__(self, execpath):
        self.execpath = execpath
        self.__datasets = zfs.Datasets()
        self.xml = gtk.glade.XML("%s/../../glade/time-slider-setup.glade" \
                                  % (os.path.dirname(__file__)))
        # signal dictionary	
        dic = {"on_ok_clicked" : self.__on_ok_clicked,
               "on_cancel_clicked" : gtk.main_quit,
               "on_snapshotmanager_delete_event" : gtk.main_quit,
               "on_enablebutton_toggled" : self.__on_enablebutton_toggled,
               "on_defaultfsradio_toggled" : self.__on_defaultfsradio_toggled,
               "on_selectfsradio_toggled" : self.__on_selectfsradio_toggled,
               "on_capspinbutton_value_changed" : self.__on_capspinbutton_value_changed,
               "on_deletesnapshots_clicked" : self.__on_deletesnapshots_clicked}
        self.xml.signal_autoconnect(dic)
        topLevel = self.xml.get_widget("toplevel")
        self._pulseDialog = self.xml.get_widget("pulsedialog")
        self._pulseDialog.set_transient_for(topLevel)

        # Used to store GUI filesystem selection state and the
        # set of intended properties to apply to zfs filesystems.
        self.uistatedic = {}
        self.fsintentdic = {}

        self.liststorefs = gtk.ListStore(bool, str, str, gobject.TYPE_PYOBJECT)
        filesystems = self.__datasets.list_filesystems()
        for fsname,fsmountpoint in filesystems:
            if (fsmountpoint == "legacy"):
                mountpoint = _("Legacy")
            else:
                mountpoint = fsmountpoint
            fs = zfs.Filesystem(fsname, fsmountpoint)
            if fs.get_auto_snap() == True:
                self.liststorefs.append([True, mountpoint, fs.name, fs])
            else:
                self.liststorefs.append([False, mountpoint, fs.name, fs])

        self.fstv = self.xml.get_widget("fstreeview")
        self.fstv.set_sensitive(False)
        # FIXME: A bit hacky but it seems to work nicely
        self.fstv.set_size_request(10,
                                   100 + (len(filesystems) - 2) *
                                   10)
        del filesystems
        self.fstv.set_model(self.liststorefs)

        self.cell0 = gtk.CellRendererToggle()
        self.cell1 = gtk.CellRendererText()
        self.cell2 = gtk.CellRendererText()
 
        self.tvradiocol = gtk.TreeViewColumn(_("Select"),
                                             self.cell0, active=0)
        self.fstv.append_column(self.tvradiocol)
        self.TvNameCol = gtk.TreeViewColumn(_("Mount Point"),
                                            self.cell1, text=1)
        self.fstv.append_column(self.TvNameCol)
        self.TvMountpointCol = gtk.TreeViewColumn(_("File System Name"),
                                                  self.cell2, text=2)
        self.fstv.append_column(self.TvMountpointCol)
        self.cell0.connect('toggled', self.__row_toggled)
        self.fsframe = self.xml.get_widget("filesysframe")
        self.fsframe.connect('unmap', self.__fsframe_unmap)

        # Initialise SMF service instance state.
        try:
            self.smfmanager = SMFManager()
        except RuntimeError,message:
            self.xml.get_widget("toplevel").set_sensitive(False)
            dialog = gtk.MessageDialog(self.xml.get_widget("toplevel"),
                                       0,
                                       gtk.MESSAGE_ERROR,
                                       gtk.BUTTONS_CLOSE,
                                       _("Snapshot manager service error"))
            dialog.format_secondary_text(_("The snapshot manager service does "
                                         "not appear to be installed on this "
                                         "system."
                                         "\n\nSee the svcs(1) man page for more "
                                         "information."
                                         "\n\nDetails:\n%s")%(message))
            dialog.run()
            sys.exit(1)

        if self.smfmanager.svcstate == "disabled":
            self.xml.get_widget("enablebutton").set_active(False)
        elif self.smfmanager.svcstate == "offline":
            self.xml.get_widget("toplevel").set_sensitive(False)
            errors = ''.join("%s\n" % (error) for error in \
                self.smfmanager.find_dependency_errors())
            dialog = gtk.MessageDialog(self.xml.get_widget("toplevel"),
                                        0,
                                        gtk.MESSAGE_ERROR,
                                        gtk.BUTTONS_CLOSE,
                                        _("Snapshot manager service dependency error"))
            dialog.format_secondary_text(_("The snapshot manager service has "
                                            "been placed offline due to a dependency "
                                            "problem. The following dependency problems "
                                            "were found:\n\n%s\n\nRun \"svcs -xv\" from "
                                            "a command prompt for more information about "
                                            "these dependency problems.") % errors)
            dialog.run()
            sys.exit(1)
        elif self.smfmanager.svcstate == "maintenance":
            self.xml.get_widget("toplevel").set_sensitive(False)
            dialog = gtk.MessageDialog(self.xml.get_widget("toplevel"),
                                        0,
                                        gtk.MESSAGE_ERROR,
                                        gtk.BUTTONS_CLOSE,
                                        _("Snapshot manager service error"))
            dialog.format_secondary_text(_("The snapshot manager service has "
                                            "encountered a problem and has been "
                                            "disabled until the problem is fixed."
                                            "\n\nSee the svcs(1) man page for more "
                                            "information."))
            dialog.run()
            sys.exit(1)
        else:
            # FIXME: Check transitional states 
            self.xml.get_widget("enablebutton").set_active(True)


        # Emit a toggled signal so that the initial GUI state is consistent
        self.xml.get_widget("enablebutton").emit("toggled")
        # Check the snapshotting policy (UserData (default), or Custom)
        if self.smfmanager.customselection == "true":
            self.xml.get_widget("selectfsradio").set_active(True)
            # Show the advanced controls so the user can see the
            # customised configuration.
            if self.smfmanager.svcstate != "disabled":
                self.xml.get_widget("expander").set_expanded(True)
        else: # "false" or any other non "true" value
            self.xml.get_widget("defaultfsradio").set_active(True)

        # Set the cleanup threshhold value
        spinButton = self.xml.get_widget("capspinbutton")
        critLevel = self.smfmanager.get_cleanup_level("critical")
        warnLevel = self.smfmanager.get_cleanup_level("warning")

        # Force the warning level to something practical
        # on the lower end, and make it no greater than the
        # critical level specified in the SVC instance.
        spinButton.set_range(70, critLevel)
        if warnLevel > 70:
            spinButton.set_value(warnLevel)
        else:
            spinButton.set_value(70)

    def __monitor_setup(self, pulseBar):
        if self._enabler.isAlive() == True:
            pulseBar.pulse()
            return True
        else:
            gtk.main_quit()   

    def __row_toggled(self, renderer, path):
        model = self.fstv.get_model()
        iter = model.get_iter(path)
        state = renderer.get_active()
        if state == False:
            self.liststorefs.set_value(iter, 0, True)
        else:
            self.liststorefs.set_value(iter, 0, False)

    def __on_ok_clicked(self, widget):
        # Make sure the dictionaries are empty.
        self.fsintentdic = {}
        self.uistatedic = {}
        enabled = self.xml.get_widget("enablebutton").get_active()
        if enabled == False:
            self.smfmanager.disable_service()
            disable_default_schedules() # auto-snapshot schedule instances
            # Ignore any possible changes to the snapshot configuration
            # of filesystems if the service is disabled.
            # So nothing else to do here.
            gtk.main_quit()
        else:
            self._pulseDialog.show()
            model = self.fstv.get_model()
            snapalldata = self.xml.get_widget("defaultfsradio").get_active()
            if snapalldata == True:
                self.smfmanager.set_selection_propval("false")
                model.foreach(self.__set_default_state)
            else:
                self.smfmanager.set_selection_propval("true")
                model.foreach(self.__get_ui_state)
            for fsname in self.uistatedic:
                self.__update_fs_state(fsname)
            self._enabler = EnableService(self)
            self._enabler.start()
            glib.timeout_add(100,
                             self.__monitor_setup,
                             self.xml.get_widget("pulsebar"))

    def __on_enablebutton_toggled(self, widget):
        expander = self.xml.get_widget("expander")    
        enabled = widget.get_active()
        self.xml.get_widget("filesysframe").set_sensitive(enabled)
        expander.set_sensitive(enabled)
        if (enabled == False):
            expander.set_expanded(False)

    def __on_defaultfsradio_toggled(self, widget):
        if widget.get_active() == True:
            self.xml.get_widget("fstreeview").set_sensitive(False)

    def __on_selectfsradio_toggled(self, widget):
       if widget.get_active() == True:
            self.xml.get_widget("fstreeview").set_sensitive(True)

    def __on_capspinbutton_value_changed(self, widget):
        value = widget.get_value_as_int()

    def __fsframe_unmap(self, widget):
        """Auto shrink the window by subtracting the frame's height
           requistion from the window's height requisition"""
        myrequest = widget.size_request()
        toplevel = self.xml.get_widget("toplevel")
        toprequest = toplevel.size_request()
        toplevel.resize(toprequest[0], toprequest[1] - myrequest[1])

    def __get_ui_state(self, model, path, iter):
        fsname = self.liststorefs.get_value(iter, 2)    
        enabled = self.liststorefs.get_value(iter, 0)
        self.uistatedic[fsname] = enabled

    def __set_default_state(self, model, path, iter):
        fsname = self.liststorefs.get_value(iter, 2)
        self.uistatedic[fsname] = True

    def __update_fs_state(self, fsname):
        selected = self.uistatedic[fsname]
        try:
            fstag = self.fsintentdic[fsname]
            # Found so we can skip over.
        except KeyError:
            # Need to check parent value to see if
            # we should set explicitly or just inherit.
            path = fsname.rsplit("/", 1)
            parentname = path[0]
            if parentname == fsname:
                # Means this filesystem is the root of the pool
                # so we need to set it explicitly.
                self.fsintentdic[fsname] = \
                    FilesystemIntention(fsname, selected, False)
            else:
                parentintent = None
                inherit = False
                # Check if parent is already set and if so whether to
                # inherit or override with a locally set property value.
                try:
                    # Parent has already been registered
                    parentintent = self.fsintentdic[parentname]
                except:
                    # Parent not yet set, so do that recursively to figure
                    # out if we need to inherit or set a local property on
                    # this child filesystem.
                    self.__update_fs_state(parentname)
                    parentintent = self.fsintentdic[parentname]
                if parentintent.selected == selected:
                    inherit = True
                self.fsintentdic[fsname] = \
                    FilesystemIntention(fsname, selected, inherit)

    def commit_filesystem_selection(self):
        """
        Commits the intended filesystem selection actions based on the
        user's UI configuration to disk
        """
        for fsname,fsmountpoint in self.__datasets.list_filesystems():
            fs = zfs.Filesystem(fsname, fsmountpoint)
            try:
                intent = self.fsintentdic[fsname]
                fs.set_auto_snap(intent.selected, intent.inherited)
            except KeyError:
                pass

    def enable_service(self):
        self.smfmanager.enable_service()

    def set_cleanup_level(self):
        """
        Wrapper function to set the warning level cleanup threshold
        value as a percentage of pool capacity.
        """
        level = self.xml.get_widget("capspinbutton").get_value_as_int()
        self.smfmanager.set_cleanup_level("warning", level)

    def __on_deletesnapshots_clicked(self, widget):
        cmdpath = os.path.join(os.path.dirname(self.execpath), \
                               "../lib/time-slider-delete")
        p = subprocess.Popen(cmdpath, close_fds=True)


class EnableService(threading.Thread):

    def __init__(self, setupManager):
        threading.Thread.__init__(self)
        self._setupManager = setupManager

    def run(self):
        try:
            # Set the service state last so that the ZFS filesystems
            # are correctly tagged before the snapshot scripts check them
            self._setupManager.commit_filesystem_selection()
            self._setupManager.set_cleanup_level()
            # First enable the auto-snapshot schedule instances
            # These are just transient SMF configuration so
            # shouldn't encounter any errors during enablement              
            enable_default_schedules()
            self._setupManager.enable_service()
        except RuntimeError,message: #FIXME Do something more meaningful
            print message


def main(argv):
    rbacp = RBACprofile()
    # The user security attributes checked are the following:
    # 1. The "Primary Administrator" role
    # 2. The "solaris.smf.manage.zfs-auto-snapshot" auth
    # 3. The "Service Management" profile
    # 4. The "ZFS Files System Management" profile.
    #
    # Valid combinations of the above are:
    # - 1
    # - 2 & 4
    # - 3 & 4
    # Note that an effective UID=0 will match any profile search so
    # no need to check it explicitly.
    if rbacp.has_profile("Primary Administrator") or \
            rbacp.has_profile("ZFS File System Management") and \
            (rbacp.has_auth("solaris.smf.manage.zfs-auto-snapshot") or \
                rbacp.has_profile("Service Management")):

        manager = SetupManager(argv)
        gtk.gdk.threads_enter()
        gtk.main()
        gtk.gdk.threads_leave()
    elif os.path.exists(argv) and os.path.exists("/usr/bin/gksu"):
        # Run via gksu, which will prompt for the root password
        os.execl("/usr/bin/gksu", "gksu", argv);
        # Shouldn't reach this point
        sys.exit(1)
    else:
        # FIXME: Pop up an error dialog and exit.
        dialog = gtk.MessageDialog(None,
                                   0,
                                   gtk.MESSAGE_ERROR,
                                   gtk.BUTTONS_CLOSE,
                                   _("Insufficient Priviliges"))
        dialog.format_secondary_text(_("The snapshot manager service requires "
                                       "administrative privileges to run. "
                                       "You have not been assigned the necessary"
                                       "administrative priviliges."
                                       "\n\nConsult your system administrator "))
        dialog.run()
        print argv + "is not a valid executable path"
        sys.exit(1)

