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

# This is the rough guess ratio used for rsync backup device size
# vs. the total size of the pools it's expected to backup.
RSYNCTARGETRATIO = 2

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

        # Currently configured rsync backup device path
        self.rsyncTargetDir = None
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
            dialog.set_icon_name("time-slider-setup")
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
            dialog.set_icon_name("time-slider-setup")
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
            dialog.set_icon_name("time-slider-setup")
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

    def __rsync_config_error(self, msg):
        topLevel = self.xml.get_widget("toplevel")
        dialog = gtk.MessageDialog(topLevel,
                                    0,
                                    gtk.MESSAGE_ERROR,
                                    gtk.BUTTONS_CLOSE,
                                    _("Unsuitable Backup Location"))
        dialog.format_secondary_text(msg)
        dialog.set_icon_name("time-slider-setup")
        dialog.run()
        dialog.hide()
        return

    def __rsync_size_warning(self, zpools, zpoolSize,
                             rsyncTarget, targetSize):
        # Using decimal "GB" instead of binary "GiB"
        KB = 1000
        MB = 1000 * KB
        GB = 1000 * MB
        TB = 1000 * GB

        suggestedSize = RSYNCTARGETRATIO * zpoolSize
        if suggestedSize > TB:
            sizeStr = "%.1f TB" % round(suggestedSize / float(TB), 1)
        elif suggestedSize > GB:
            sizeStr = "%.1f GB" % round(suggestedSize / float(GB), 1)
        else:
            sizeStr = "%.1f MB" % round(suggestedSize / float(MB), 1)

        if targetSize > TB:
            targetStr = "%.1f TB" % round(targetSize / float(TB), 1)
        elif targetSize > GB:
            targetStr = "%.1f GB" % round(targetSize / float(GB), 1)
        else:
            targetStr = "%.1f MB" % round(targetSize / float(MB), 1)


        msg = _("Time Slider suggests a device with a capacity of at "
                "least <b>%s</b>.\n"
                "The device: \'<b>%s</b>\'\nonly has <b>%s</b>\n"
                "Do you want to use it anyway?") \
                % (sizeStr, rsyncTarget, targetStr)

        topLevel = self.xml.get_widget("toplevel")
        dialog = gtk.MessageDialog(topLevel,
                                   0,
                                   gtk.MESSAGE_QUESTION,
                                   gtk.BUTTONS_YES_NO,
                                   _("Time Slider"))
        dialog.set_default_response(gtk.RESPONSE_NO)
        dialog.set_transient_for(topLevel)
        dialog.set_markup(msg)
        dialog.set_icon_name("time-slider-setup")
        container = dialog.get_content_area()

        response = dialog.run()
        dialog.hide()
        if response == gtk.RESPONSE_YES:
            return True
        else:
            return False

    def __check_rsync_config(self):
        """
           Checks rsync configuration including, filesystem selection,
           target directory validation and capacity checks.
           Returns True if everything is OK, otherwise False.
           Pops up blocking error dialogs to notify users of error
           conditions before returning.
        """
        def _get_mount_point(path):
            if os.path.ismount(path):
                return path
            else:
                return _get_mount_point(join(path, pardir))

        if self.rsyncEnabled != True:
            return True
        # FIXME - perform the swathe of validation checks on the
        # target directory for rsync here
        rsyncChooser = self.xml.get_widget("rsyncchooser")
        newTargetDir = rsyncChooser.get_file().get_path()

        # We require the whole device. So find the enclosing
        # mount point and inspect from there.
        targetMountPoint = abspath(_get_mount_point(newTargetDir))

        # Check that selected directory is either empty
        # or already preconfigured as a backup target
        sys,nodeName,rel,ver,arch = os.uname()
        basePath = os.path.join(targetMountPoint,
                                rsyncsmf.RSYNCDIRPREFIX)
        nodePath = os.path.join(basePath,
                                nodeName)
        configPath = os.path.join(basePath,
                                    rsyncsmf.RSYNCCONFIGFILE)
        self.newRsyncTarget = True
        targetDirKey = None

        contents = os.listdir(targetMountPoint)
        os.chdir(targetMountPoint)

        # The only other exception to an empty directory is
        # "lost+found".
        for item in contents:
            if (item != rsyncsmf.RSYNCDIRPREFIX and \
                item != "lost+found") or \
               not os.path.isdir(item) or \
               os.path.islink(item):
                msg = _("\'%s\'\n is not an empty device.\n\n"
                        "Please select an empty device.") \
                        % (newTargetDir)
                self.__rsync_config_error(msg)
                return False

        # Validate existing directory structure
        if os.path.exists(basePath):
            # We only accept a pre-existing directory if
            # 1. It has a config key that matches that stored by
            #    the rsync plugin's SMF configuration
            # 2. It has a single subfolder that matches the nodename
            #    of this system,

            # Check for previous config key
            if os.path.exists(configPath):
                f = open(configPath, 'r')
                for line in f.readlines():
                    key, val = line.strip().split('=')
                    if key.strip() == "target_key":
                        targetDirKey = val.strip()
                        break
            self._smfTargetKey = self.rsyncSMF.get_target_key()

            # Examine anything else in the directory
            self._targetSelectionError = None
            dirList = [d for d in os.listdir(basePath) if
                        d != '.rsync-config']
            os.chdir(basePath)
            if len(dirList) > 0:
                msg = _("\'%s\'\n is not an empty device.\n\n"
                        "Please select an empty device.") \
                        % (newTargetDir)
                # No config key or > 1 directory:
                # User specified a non empty directory.
                if targetDirKey == None or len(dirList) > 1:
                    self.__rsync_config_error(msg)
                    return False
                # Make sure the single item is not a file or symlink.
                elif os.path.islink(dirList[0]) or \
                        os.path.isfile(dirList[0]):
                    self.__rsync_config_error(msg)
                    return False
                else:
                    # Has 1 other item and a config key. Other
                    # item must be a directory and must match the
                    # system nodename and SMF's key value respectively
                    # respectively
                    if dirList[0] != nodeName or \
                        targetDirKey != self._smfTargetKey:
                        msg = _("\'%s\'\n"
                                "is a Time Slider external backup device "
                                "that is already in use by another system. "
                                "Backup devices may not be shared between "
                                "systems." 
                                "\n\nPlease use a different device.") \
                                % (newTargetDir)
                        self.__rsync_config_error(msg)                                
                        return False
                    else:
                        # Appears to be our own pre-configured directory.
                        self.newRsyncTarget = False

        # If it's a new directory check that it's writable.
        if self.newRsyncTarget == True:
            f = None
            testFile = os.path.join(targetMountPoint, ".ts-test")
            try:
                f = open(testFile, 'w')
            except (OSError, IOError):
                msg = _("\'%s\'\n"
                        "is not writable. The backup device must "
                        "be writeable by the system admistrator." 
                        "\n\nPlease use a different device.") \
                        % (targetMountPoint)
                self.__rsync_config_error(msg)
                return False
            f.close()

            # Try to create a symlink. Rsync requires this to
            # do incremental backups and to ensure it's posix like
            # enough to correctly set file ownerships and perms.
            os.chdir(targetMountPoint)
            try:
                os.link(testFile, ".ts-test-link")
            except OSError:
                msg = _("\'%s\'\n"
                        "contains an incompatible file system. " 
                        "The selected device must have a Unix "
                        "style file system that supports file "
                        "linking, such as UFS"
                        "\n\nPlease use a different device.") \
                        % (targetMountPoint)
                self.__rsync_config_error(msg)
                return False
            finally:
                os.unlink(testFile)
            os.unlink(".ts-test-link")


        # Compare device ID against selected ZFS filesystems
        # and their enclosing Zpools. The aim is to avoid
        # a vicous circle caused by backing up snapshots onto
        # the same pool the snapshots originate from
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
                msg = _("\'%s\'\n"
                        "belongs to the ZFS filesystem \'%s\' "
                        "which is already selected for "
                        "regular ZFS snaphots." 
                        "\n\nPlease select a drive "
                        "not already in use by "
                        "Time Slider") \
                        % (newTargetDir, fs.name)
                self.__rsync_config_error(msg)
                return False
            else:
                # See if there is anything else on the pool being
                # snapshotted
                poolName = fs.name.split("/", 1)[0]
                for name,mount in self.__datasets.list_filesystems():
                    if name.find(poolName) == 0:
                        try:
                            otherEnabled = self.snapstatedic[name]
                            radioBtn = self.xml.get_widget("defaultfsradio")
                            snapAll = radioBtn.get_active()
                            if snapAll or otherEnabled:
                                msg = _("\'%s\'\n"
                                        "belongs to the ZFS pool \'%s\' "
                                        "which is already being used "
                                        "to store ZFS snaphots." 
                                        "\n\nPlease select a drive "
                                        "not already in use by "
                                        "Time Slider") \
                                        % (newTargetDir, poolName)
                                self.__rsync_config_error(msg)
                                return False
                        except KeyError:
                            pass               
        except KeyError:
            # No match found - good.
            pass


        # Figure out if there's a reasonable amount of free space to
        # store backups. This is a vague guess at best.
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
        targetAvail = util.get_available_size(targetMountPoint)
        targetUsed = util.get_used_size(targetMountPoint)
        targetSum = targetAvail + targetUsed

        # Recommended Minimum:
        # At least double the combined size of all pools with
        # fileystems selected for backup. Variables include,
        # frequency of data changes, how much efficiency rsync
        # sacrifices compared to ZFS' block level diff tracking,
        # whether compression and/or deduplication are enabled 
        # on the source pool/fileystem.
        # We don't try to make calculations based on individual
        # filesystem selection as there are too many unpredictable
        # variables to make an estimation of any practical use.
        # Let the user figure that out for themselves.

        # The most consistent measurement is to use the sum of
        # available and used size on the target fileystem. We
        # assume based on previous checks that the target device
        # is only being used for rsync backups and therefore the
        # used value consists of existing backups and is. Available
        # space can be reduced for various reasons including the used
        # value increasing or for nfs mounted zfs fileystems, other
        # zfs filesystems on the containing pool using up more space.
        

        targetPoolRatio = targetSum/float(sumPoolSize)
        if (targetPoolRatio < RSYNCTARGETRATIO):
            response = self.__rsync_size_warning(snapPools,
                                                 sumPoolSize,
                                                 targetMountPoint,
                                                 targetSum)
            if response == False:
                return False

        self.rsyncTargetDir = targetMountPoint
        return True

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
            if self.rsyncEnabled and \
               not self.__check_rsync_config():
                    return

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

    def setup_rsync_config(self):
        if self.rsyncEnabled == True:
            sys,nodeName,rel,ver,arch = os.uname()
            basePath = os.path.join(self.rsyncTargetDir,
                                    rsyncsmf.RSYNCDIRPREFIX,)
            nodePath = os.path.join(basePath,
                                    nodeName)
            configPath = os.path.join(basePath,
                                        rsyncsmf.RSYNCCONFIGFILE)
            newKey = generate_random_key()
            try:
                origmask = os.umask(0222)
                if not os.path.exists(nodePath):
                    os.makedirs(nodePath, 0755)
                f = open(configPath, 'w')
                f.write("target_key=%s\n" % (newKey))
                f.close()
                os.umask(origmask)
            except OSError as e:
                # Drop the pulse dialog and pop up error dialog
                self._pulseDialog.hide()
                sys.stderr.write("Error configuring external backup device:\n"
                        "%s\n\nReason:\n %s") \
                        % (self.rsyncTargetDir, str(e))
                sys.exit(-1)
            self.rsyncSMF.set_target_dir(self.rsyncTargetDir)
            self.rsyncSMF.set_target_key(newKey)
            self.rsyncSMF.enable_service()
        else:
            self.rsyncSMF.disable_service()
        return

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
            self._setupManager.setup_rsync_config()
            # First enable the auto-snapshot schedule instances
            # These are just transient SMF configuration so
            # shouldn't encounter any errors during enablement              
            enable_default_schedules()
            self._setupManager.enable_service()
        except RuntimeError, message: #FIXME Do something more meaningful
            sys.stderr.write(str(message))

def generate_random_key(length=32):
    """
    Returns a 'length' byte character composed of random letters and
    unsigned single digit integers. Used to create a random
    signature key to identify pre-configured backup directories
    for the rsync plugin
    """
    from string import letters, digits
    from random import choice
    return ''.join([choice(letters + digits) \
              for i in range(length)])

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
        dialog.set_icon_name("time-slider-setup")
        dialog.run()
        sys.exit(1)

