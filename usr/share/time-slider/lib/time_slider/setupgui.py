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
import util
import smf
from autosnapsmf import enable_default_schedules, disable_default_schedules

from os.path import abspath, dirname, join, pardir
sys.path.insert(0, join(dirname(__file__), pardir, "plugin"))
import plugin
from os.path import abspath, dirname, join, pardir
sys.path.insert(0, join(dirname(__file__), pardir, "plugin", "rsync"))
import rsyncsmf

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
from timeslidersmf import TimeSliderSMF
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
               "on_rsyncbutton_toggled" : self.__on_rsyncbutton_toggled,
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
        self.snapstatedic = {}
        self.fsintentdic = {}
        self.rsyncintentdic = {}
        # Dictionary that maps device ID numbers to zfs filesystem objects
        self.fsDevices = {}

        self.liststorefs = gtk.ListStore(bool,
                                         bool,
                                         str,
                                         str,
                                         gobject.TYPE_PYOBJECT)
        filesystems = self.__datasets.list_filesystems()
        for fsname,fsmountpoint in filesystems:
            if (fsmountpoint == "legacy"):
                mountpoint = _("Legacy")
            else:
                mountpoint = fsmountpoint
            fs = zfs.Filesystem(fsname, fsmountpoint)
            # Note that we don't deal support legacy mountpoints.
            if fsmountpoint != "legacy" and fs.is_mounted():
                self.fsDevices[os.stat(fsmountpoint).st_dev] = fs
            snap = fs.get_auto_snap()
            rsyncstr = fs.get_user_property(rsyncsmf.RSYNCFSTAG)
            if rsyncstr == "true":
                rsync = True
            else:
                rsync = False
            # Rsync is only performed on snapshotted filesystems.
            # So treat as False if rsync is set to true independently
            self.liststorefs.append([snap, snap & rsync,
                                     mountpoint, fs.name, fs])
                
        self.fstv = self.xml.get_widget("fstreeview")
        self.fstv.set_sensitive(False)
        # FIXME: A bit hacky but it seems to work nicely
        self.fstv.set_size_request(10,
                                   100 + (len(filesystems) - 2) *
                                   10)
        del filesystems
        self.fstv.set_model(self.liststorefs)

        self.cell0 = gtk.CellRendererToggle()
        self.cell1 = gtk.CellRendererToggle()
        self.cell2 = gtk.CellRendererText()
        self.cell3 = gtk.CellRendererText()
 
        self.tvradiocol = gtk.TreeViewColumn(_("Select"),
                                             self.cell0, active=0)
        self.fstv.insert_column(self.tvradiocol, 0)

        self.rsyncradiocol = gtk.TreeViewColumn(_("Replicate"),
                                             self.cell1, active=1)

        self.TvNameCol = gtk.TreeViewColumn(_("Mount Point"),
                                            self.cell2, text=2)
        self.fstv.insert_column(self.TvNameCol, 2)
        self.TvMountpointCol = gtk.TreeViewColumn(_("File System Name"),
                                                  self.cell3, text=3)
        self.fstv.insert_column(self.TvMountpointCol, 3)
        self.cell0.connect('toggled', self.__row_toggled)
        self.cell1.connect('toggled', self.__rsync_cell_toggled)
        advancedbox = self.xml.get_widget("advancedbox")
        advancedbox.connect('unmap', self.__advancedbox_unmap)  

        self.rsyncSMF = rsyncsmf.RsyncSMF("%s:rsync" \
                                          %(plugin.PLUGINBASEFMRI))
        state = self.rsyncSMF.get_service_state()
        self.rsyncTargetDir = self.rsyncSMF.get_target_dir()

        rsyncChooser = self.xml.get_widget("rsyncchooser")
        rsyncChooser.set_current_folder(self.rsyncTargetDir)

        if state != "disabled":
            self.rsyncEnabled = True
            self.xml.get_widget("rsyncbutton").set_active(True)
        else:
            self.rsyncEnabled = False
            rsyncChooser.set_sensitive(False)

        # Initialise SMF service instance state.
        try:
            self.sliderSMF = TimeSliderSMF()
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

        if self.sliderSMF.svcstate == "disabled":
            self.xml.get_widget("enablebutton").set_active(False)
        elif self.sliderSMF.svcstate == "offline":
            self.xml.get_widget("toplevel").set_sensitive(False)
            errors = ''.join("%s\n" % (error) for error in \
                self.sliderSMF.find_dependency_errors())
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
        elif self.sliderSMF.svcstate == "maintenance":
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
        if self.sliderSMF.is_custom_selection() == True:
            self.xml.get_widget("selectfsradio").set_active(True)
            # Show the advanced controls so the user can see the
            # customised configuration.
            if self.sliderSMF.svcstate != "disabled":
                self.xml.get_widget("expander").set_expanded(True)
        else: # "false" or any other non "true" value
            self.xml.get_widget("defaultfsradio").set_active(True)

        # Set the cleanup threshhold value
        spinButton = self.xml.get_widget("capspinbutton")
        critLevel = self.sliderSMF.get_cleanup_level("critical")
        warnLevel = self.sliderSMF.get_cleanup_level("warning")

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
            self.liststorefs.set_value(iter, 1, False)

    def __rsync_cell_toggled(self, renderer, path):
        model = self.fstv.get_model()
        iter = model.get_iter(path)
        state = renderer.get_active()
        rowstate = self.liststorefs.get_value(iter, 0)
        if rowstate == True:
            if state == False:
                self.liststorefs.set_value(iter, 1, True)
            else:
                self.liststorefs.set_value(iter, 1, False)

    def __on_ok_clicked(self, widget):
        # Make sure the dictionaries are empty.
        self.fsintentdic = {}
        self.snapstatedic = {}
        self.rsyncstatedic = {}
        enabled = self.xml.get_widget("enablebutton").get_active()
        self.rsyncEnabled = self.xml.get_widget("rsyncbutton").get_active()
        if enabled == False:
            self.sliderSMF.disable_service()
            self.rsyncSMF.disable_service()
            disable_default_schedules() # auto-snapshot schedule instances
            # Ignore any possible changes to the snapshot configuration
            # of filesystems if the service is disabled.
            # So nothing else to do here.
            gtk.main_quit()
        else:
            model = self.fstv.get_model()
            snapalldata = self.xml.get_widget("defaultfsradio").get_active()
                
            if snapalldata == True:
                self.sliderSMF.set_custom_selection(False)
                model.foreach(self.__set_fs_selection_state, True)
                if self.rsyncEnabled == True:
                    model.foreach(self.__set_rsync_selection_state, True)
            else:
                self.sliderSMF.set_custom_selection(True)
                model.foreach(self.__get_fs_selection_state)
                model.foreach(self.__get_rsync_selection_state)
            for fsname in self.snapstatedic:
                self.__refine_filesys_actions(fsname,
                                              self.snapstatedic,
                                              self.fsintentdic)
                if self.rsyncEnabled == True:
                    self.__refine_filesys_actions(fsname,
                                                  self.rsyncstatedic,
                                                  self.rsyncintentdic)
            if self.rsyncEnabled == True:
                # FIXME - perform the swathe of validation checks on the
                # target directory for rsync here
                rsyncChooser = self.xml.get_widget("rsyncchooser")
                newTargetDir = rsyncChooser.get_file().get_path()
                self.rsyncTargetDir = newTargetDir

                # Get device ID of rsync target dir.
                targetDev = os.stat(newTargetDir).st_dev
                try:
                    fs = self.fsDevices[targetDev]
                    
                    # See if the filesystem itself is selected
                    # and/or any other fileystem on the pool is 
                    # selected.
                    fsEnabled = self.snapstatedic[fs.name]
                    if fsEnabled == True:
                        # Definitely can't use this since it's a
                        # snapshotted filesystem.
                        print "Can't use snapshotted filesystem: " + fs.name
                        msg = _("\'%s\'\n"
                              "belongs to the ZFS filesystem \'%s\' "
                              "which is already selected for "
                              "regular ZFS snaphots." 
                              "\n\nPlease select a drive "
                              "not already in use by "
                              "Time Slider") \
                              % (newTargetDir, fs.name)
                        topLevel = self.xml.get_widget("toplevel")
                        dialog = gtk.MessageDialog(topLevel,
                                                   0,
                                                   gtk.MESSAGE_ERROR,
                                                   gtk.BUTTONS_CLOSE,
                                                   _("Unsuitable Backup Location"))
                        dialog.format_secondary_text(msg)
                        dialog.run()
                        dialog.hide()
                        return
                    else:
                        # See if there is anything else on the pool being
                        # snapshotted
                        poolName = fs.name.split("/", 1)[0]
                        for name,mount in self.__datasets.list_filesystems():
                            if name.find(poolName) == 0:
                                try:
                                    otherEnabled = self.snapstatedic[name]
                                    if snapalldata or otherEnabled:
                                        msg = _("\'%s\'\n"
                                              "belongs to the ZFS pool \'%s\' "
                                              "which is already being used "
                                              "to store ZFS snaphots." 
                                              "\n\nPlease select a drive "
                                              "not already in use by "
                                              "Time Slider") \
                                              % (newTargetDir, poolName)
                                        topLevel = self.xml.get_widget("toplevel")
                                        dialog = gtk.MessageDialog(topLevel,
                                                    0,
                                                    gtk.MESSAGE_ERROR,
                                                    gtk.BUTTONS_CLOSE,
                                                    _("Unsuitable Backup Location"))
                                        dialog.format_secondary_text(msg)
                                        dialog.run()
                                        dialog.hide()
                                        return
                                except KeyError:
                                    pass               
                except KeyError:
                    # No match found - good.
                    pass

                # Next figure out if there's a reasonable amount of free space
                # to store backups. We need to figure out an absolute minimum
                # requirement as well as a recommended minimum.
                
                allPools = zfs.list_zpools()
                snapPools = []
                # FIXME -  this is for custom selection. There is a short
                # circuit case for default (All) configuration. Don't forget
                # to implement this short circuit.
                for poolName in allPools:
                    try:
                        snapPools.index(poolName)
                    except ValueError:
                        pool = zfs.ZPool(poolName)
                        # FIXME - we should include volumes here but they
                        # can only be set from the command line, not via
                        # the GUI, so not crucial.
                        for fsName,mount in pool.list_filesystems():
                            # Don't try to catch exception. The filesystems
                            # are already populated in self.snapstatedic
                            enabled = self.snapstatedic[fsName]
                            if enabled == True:
                                snapPools.append(poolName)
                                break

                sumPoolSize = 0
                for poolName in snapPools:
                    pool = zfs.ZPool(poolName)
                    # Rough calcualation, but precise enough for
                    # estimation purposes
                    sumPoolSize += pool.get_used_size()
                    sumPoolSize += pool.get_available_size()

                # Compare with available space on rsync target dir
                targetDirAvail = util.get_available_size(newTargetDir)
                
                # FIXME - need to figure out a way to not complain when 
                # user is re-enabling the rsync plugin and reusing a 
                # previously preconfigured backup directory. Perhaps
                # leave a hostid stamp in the target directory.
                ratio = targetDirAvail/float(sumPoolSize)

                # Create the subdirectory underneath the target directory
                # selected by the user if necessary "TIMESLIDER/<nodename>"
                sys,nodeName,rel,ver,arch = os.uname()
                fullPath = os.path.join(newTargetDir,
                                        rsyncsmf.RSYNCDIRPREFIX,
                                        nodeName)
                if not os.path.exists(fullPath):
                    os.makedirs(fullPath, 0755)

            self._pulseDialog.show()
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
        self.enabled = enabled
        if (enabled == False):
            expander.set_expanded(False)

    def __on_rsyncbutton_toggled(self, widget):
        self.rsyncEnabled = widget.get_active()
        if self.rsyncEnabled == True:
            self.fstv.insert_column(self.rsyncradiocol, 1)
            self.xml.get_widget("rsyncchooser").set_sensitive(True)
        else:
            self.fstv.remove_column(self.rsyncradiocol)
            self.xml.get_widget("rsyncchooser").set_sensitive(False)

    def __on_defaultfsradio_toggled(self, widget):
        if widget.get_active() == True:
            self.xml.get_widget("fstreeview").set_sensitive(False)

    def __on_selectfsradio_toggled(self, widget):
       if widget.get_active() == True:
            self.xml.get_widget("fstreeview").set_sensitive(True)

    def __on_capspinbutton_value_changed(self, widget):
        value = widget.get_value_as_int()

    def __advancedbox_unmap(self, widget):
        # Auto shrink the window by subtracting the frame's height
        # requistion from the window's height requisition
        myrequest = widget.size_request()
        toplevel = self.xml.get_widget("toplevel")
        toprequest = toplevel.size_request()
        toplevel.resize(toprequest[0], toprequest[1] - myrequest[1])

    def __get_fs_selection_state(self, model, path, iter):
        fsname = self.liststorefs.get_value(iter, 3)    
        enabled = self.liststorefs.get_value(iter, 0)
        self.snapstatedic[fsname] = enabled

    def __get_rsync_selection_state(self, model, path, iter):
        fsname = self.liststorefs.get_value(iter, 3)
        enabled = self.liststorefs.get_value(iter, 1)
        self.rsyncstatedic[fsname] = enabled

    def __set_fs_selection_state(self, model, path, iter, selected):
        fsname = self.liststorefs.get_value(iter, 3)
        self.snapstatedic[fsname] = selected

    def __set_rsync_selection_state(self, model, path, iter, selected):
        fsname = self.liststorefs.get_value(iter, 3)
        self.rsyncstatedic[fsname] = selected

    def __refine_filesys_actions(self, fsname, inputdic, actions):
        selected = inputdic[fsname]
        try:
            fstag = actions[fsname]
            # Found so we can skip over.
        except KeyError:
            # Need to check parent value to see if
            # we should set explicitly or just inherit.
            path = fsname.rsplit("/", 1)
            parentname = path[0]
            if parentname == fsname:
                # Means this filesystem is the root of the pool
                # so we need to set it explicitly.
                actions[fsname] = \
                    FilesystemIntention(fsname, selected, False)
            else:
                parentintent = None
                inherit = False
                # Check if parent is already set and if so whether to
                # inherit or override with a locally set property value.
                try:
                    # Parent has already been registered
                    parentintent = actions[parentname]
                except:
                    # Parent not yet set, so do that recursively to figure
                    # out if we need to inherit or set a local property on
                    # this child filesystem.
                    self.__refine_filesys_actions(parentname,
                                                  inputdic,
                                                  actions)
                    parentintent = actions[parentname]
                if parentintent.selected == selected:
                    inherit = True
                actions[fsname] = \
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

    def commit_rsync_selection(self):
        """
        Commits the intended filesystem selection actions based on the
        user's UI configuration to disk
        """
        for fsname,fsmountpoint in self.__datasets.list_filesystems():
            fs = zfs.Filesystem(fsname, fsmountpoint)
            try:
                intent = self.rsyncintentdic[fsname]
                if intent.inherited == True:
                    fs.unset_user_property("org.opensolaris:time-slider-rsync")
                else:
                    if intent.selected == True:
                        value = "true"
                    else:
                        value = "false"
                    fs.set_user_property("org.opensolaris:time-slider-rsync",
                                         value)
            except KeyError:
                pass

    def enable_service(self):
        if self.rsyncEnabled == True:
            self.rsyncSMF.enable_service()
        else:
            self.rsyncSMF.disable_service()
        self.sliderSMF.enable_service()


    def set_cleanup_level(self):
        """
        Wrapper function to set the warning level cleanup threshold
        value as a percentage of pool capacity.
        """
        level = self.xml.get_widget("capspinbutton").get_value_as_int()
        self.sliderSMF.set_cleanup_level("warning", level)

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
            self._setupManager.commit_rsync_selection()
            self._setupManager.set_cleanup_level()
            rsyncSMF = self._setupManager.rsyncSMF
            rsyncTargetDir = self._setupManager.rsyncTargetDir
            rsyncSMF.set_target_dir(rsyncTargetDir)
            # First enable the auto-snapshot schedule instances
            # These are just transient SMF configuration so
            # shouldn't encounter any errors during enablement              
            enable_default_schedules()
            self._setupManager.enable_service()
        except RuntimeError,message: #FIXME Do something more meaningful
            print message


def main(argv):
    rbacp = RBACprofile()
    # The setup GUI needs to be run as root in order to ensure
    # that the rsync backup target directory is accessible by
    # root and to perform validation checks on it.
    # This GUI can be launched with an euid of root in one of
    # the following 3 ways;
    # 0. Run by the superuser (root)
    # 1. Run by a user assigned "Primary Administrator" profile.
    # 3. Run via gksu to allow a non priviliged user to authenticate
    #    as the superuser (root)

    if os.geteuid() == 0:
        manager = SetupManager(argv)
        gtk.gdk.threads_enter()
        gtk.main()
        gtk.gdk.threads_leave()
    elif rbacp.has_profile("Primary Administrator"):
        # Run via pfexec, which will launch the GUI as superuser
        os.execl("/usr/bin/pfexec", "pfexec", argv)
        # Shouldn't reach this point
        sys.exit(1)
    elif os.path.exists(argv) and os.path.exists("/usr/bin/gksu"):
        # Run via gksu, which will prompt for the root password
        os.execl("/usr/bin/gksu", "gksu", argv)
        # Shouldn't reach this point
        sys.exit(1)
    else:
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
        sys.exit(1)

