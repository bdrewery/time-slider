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
import subprocess
import gobject
import dbus
import dbus.decorators
import dbus.glib
import dbus.mainloop
import dbus.mainloop.glib
import gtk
import pygtk
import pynotify

from time_slider import util

from os.path import abspath, dirname, join, pardir
sys.path.insert(0, join(dirname(__file__), pardir, "plugin"))
import plugin
sys.path.insert(0, join(dirname(__file__), pardir, "plugin", "rsync"))
import backup

class Note:

    def __init__(self, icon, menu):
        self._note = None
        self._msgDialog = None
        self._cleanup_head = None
        self._cleanup_body = None
        self._menu = menu
        self._icon = icon
        self._icon.connect("popup-menu", self._activate_menu)
        self._icon.set_visible(True)

    def _activate_menu(self, icon, button, time):
        if button == 3:
            self._menu.popup(None, None,
                             gtk.status_icon_position_menu,
                             button, time, icon)

    def _dialog_response(self, dialog, response):
        dialog.destroy()

    def _notification_closed(self, notifcation):
        self._note = None

    def _show_notification(self):
        if self._icon.is_embedded() == True:
            self._note.attach_to_status_icon(self._icon)
        self._note.show()
        return False

    def _connect_to_object(self):
        pass

    def _watch_handler(self, new_owner = None):
        if new_owner == None or len(new_owner) == 0:
            pass
        else:
            self._connect_to_object()

    def _setup_icon_for_note(self): 
        iconTheme = gtk.icon_theme_get_default()
        pixbuf = iconTheme.load_icon("gnome-dev-harddisk", 48, 0)
        self._note.set_category("device")
        self._note.set_icon_from_pixbuf(pixbuf)


class RsyncNote(Note):

    def __init__(self, icon, menu):
        Note.__init__(self, icon, menu)
        dbus.bus.NameOwnerWatch(bus,
                                "org.opensolaris.TimeSlider.plugin.rsync",
                                self._watch_handler)
        # Every time the rsync backup script runs it will
        # register with d-bus and trigger self._watch_handler().
        # Use this variable to keep track of it's running status.
        self._scriptRunning = False
        self._syncNowItem = gtk.MenuItem(_("Synchronise Now"))
        self._syncNowItem.set_sensitive(False)
        self._syncNowItem.connect("activate",
                                  self._sync_now)
        self._syncNowItem.show()
        self._menu.append(self._syncNowItem)
        # Kick start things by initially obtaining the
        # backlog size and triggering a callback.
        # Signal handlers will keep tooltip status up
        # to date afterwards when the backup cron job
        # executes.
        propName = "%s:rsync" % (backup.propbasename)
        queue = backup.list_pending_snapshots(propName)
        self.queueSize = len(queue)
        if self.queueSize == 0:
            self._rsync_synced_handler()
        else:
            self._rsync_unsynced_handler(self.queueSize)            

    def _watch_handler(self, new_owner = None):
        if new_owner == None or len(new_owner) == 0:
            # Script not running or exited
            self._scriptRunning = False
            self._syncNowItem.set_sensitive(True)
        else:
            self._scriptRunning = True
            self._syncNowItem.set_sensitive(False)
            self._connect_to_object()

    def _rsync_started_handler(self, target, sender=None, interface=None, path=None):
        urgency = pynotify.URGENCY_NORMAL
        if (self._note != None):
            self._note.close()
        self._note = pynotify.Notification(_("Backup Started"),
                                           _("Backing up snapshots to: \'%s\'\n" \
                                           "Please do not disconnect the backup device") \
                                            % (target))
        self._note.connect("closed", \
                           self._notification_closed)
        self._note.set_urgency(urgency)
        self._setup_icon_for_note()
        gobject.idle_add(self._show_notification)

    def _rsync_current_handler(self, snapshot, remaining, sender=None, interface=None, path=None):
        self._icon.set_tooltip_markup(_("Backing up: <b>\'%s\'\n%d</b> snapshots remaining.") \
                                      % (snapshot, remaining))

    def _rsync_complete_handler(self, target, sender=None, interface=None, path=None):
        urgency = pynotify.URGENCY_NORMAL
        if (self._note != None):
            self._note.close()
        self._note = pynotify.Notification(_("Backup Complete"),
                                           _("Your snapshots have been backed up to: \'%s\'") \
                                           % (target))
        self._note.connect("closed", \
                           self._notification_closed)
        self._note.set_urgency(urgency)
        self._setup_icon_for_note()
        self._icon.set_has_tooltip(False)
        self.queueSize = 0
        gobject.idle_add(self._show_notification)

    def _rsync_synced_handler(self, sender=None, interface=None, path=None):
        self._icon.set_tooltip_markup(_("Your backups are up to date."))
        self.queueSize = 0

    def _rsync_unsynced_handler(self, queueSize, sender=None, interface=None, path=None):
        self._icon.set_tooltip_markup(_("%d snapshots are queued for backup.") \
                                      % (queueSize))
        self.queueSize = queueSize

    def _connect_to_object(self):
        try:
            remote_object = bus.get_object("org.opensolaris.TimeSlider.plugin.rsync",
                                           "/org/opensolaris/TimeSlider/plugin/rsync")
        except dbus.DBusException:
            print "Failed to connect to remote D-Bus object: %s" % \
                    ("/org/opensolaris/TimeSlider/plugin/rsync")
            return

        #Create an Interface wrapper for the remote object
        iface = dbus.Interface(remote_object, "org.opensolaris.TimeSlider.plugin.rsync")

        iface.connect_to_signal("rsync_started", self._rsync_started_handler, sender_keyword='sender',
                                interface_keyword='interface', path_keyword='path')
        iface.connect_to_signal("rsync_current", self._rsync_current_handler, sender_keyword='sender',
                                interface_keyword='interface', path_keyword='path')
        iface.connect_to_signal("rsync_complete", self._rsync_complete_handler, sender_keyword='sender',
                                interface_keyword='interface', path_keyword='path')
        iface.connect_to_signal("rsync_synced", self._rsync_synced_handler, sender_keyword='sender',
                                interface_keyword='interface', path_keyword='path')
        iface.connect_to_signal("rsync_unsynced", self._rsync_unsynced_handler, sender_keyword='sender',
                                interface_keyword='interface', path_keyword='path')

    def _sync_now(self, menuItem):
        # FIXME This is a placeholder. The actual proper implementation will need to
        # do some privilige checking and should ideally check if the backup target
        # is accessible before proceeding
        cmd = ["/usr/bin/pfexec", "/usr/lib/time-slider/plugins/rsync/rsync-backup", \
               "%s:rsync" % (plugin.PLUGINBASEFMRI)]
        subprocess.Popen(cmd, close_fds=True, cwd="/")

class CleanupNote(Note):

    def __init__(self, icon, menu):
        Note.__init__(self, icon, menu)
        dbus.bus.NameOwnerWatch(bus,
                                "org.opensolaris.TimeSlider",
                                self._watch_handler)

    def _show_cleanup_details(self, *args):
        # We could keep a dialog around but this a rare
        # enough event that's it not worth the effort.
        dialog = gtk.MessageDialog(type=gtk.MESSAGE_WARNING,
                                   buttons=gtk.BUTTONS_CLOSE)
        dialog.set_title(_("Time Slider: Low Space Warning"))
        dialog.set_markup("<b>%s</b>" % (self._cleanup_head))
        dialog.format_secondary_markup(self._cleanup_body)
        dialog.show()
        dialog.present()
        dialog.connect("response", self._dialog_response)

    def _cleanup_handler(self, pool, severity, threshhold, sender=None, interface=None, path=None):
        if severity == 4:
            expiry = pynotify.EXPIRES_NEVER
            urgency = pynotify.URGENCY_CRITICAL
            self._cleanup_head = _("Emergency: \'%s\' is full!") % pool
            notifyBody = _("The file system: \'%s\', is over %s%% full.") \
                            % (pool, threshhold)
            self._cleanup_body = _("The file system: \'%s\', is over %s%% full.\n"
                     "As an emergency measure, Time Slider has "
                     "destroyed all of its backups.\nTo fix this problem, "
                     "delete any unnecessary files on \'%s\', or add "
                     "disk space (see ZFS documentation).") \
                      % (pool, threshhold, pool)
        elif severity == 3:
            expiry = pynotify.EXPIRES_NEVER
            urgency = pynotify.URGENCY_CRITICAL
            self._cleanup_head = _("Emergency: \'%s\' is almost full!") % pool
            notifyBody = _("The file system: \'%s\', exceeded %s%% "
                           "of its total capacity") \
                            % (pool, threshhold)
            self._cleanup_body = _("The file system: \'%s\', exceeded %s%% "
                     "of its total capacity. As an emerency measure, "
                     "Time Slider has has destroyed most or all of its "
                     "backups to prevent the disk becoming full. "
                     "To prevent this from happening again, delete "
                     "any unnecessary files on \'%s\', or add disk "
                     "space (see ZFS documentation).") \
                      % (pool, threshhold, pool)
        elif severity == 2:
            expiry = pynotify.EXPIRES_NEVER
            urgency = pynotify.URGENCY_CRITICAL
            self._cleanup_head = _("Urgent: \'%s\' is almost full!") % pool
            notifyBody = _("The file system: \'%s\', exceeded %s%% "
                           "of its total capacity") \
                            % (pool, threshhold)
            self._cleanup_body = _("The file system: \'%s\', exceeded %s%% "
                     "of its total capacity. As a remedial measure, "
                     "Time Slider has destroyed some backups, and will "
                     "destroy more, eventually all, as capacity continues "
                     "to diminish.\nTo prevent this from happening again, "
                     "delete any unnecessary files on \'%s\', or add disk "
                     "space (see ZFS documentation).") \
                     % (pool, threshhold, pool)
        elif severity == 1:
            expiry = 20000 # 20 seconds
            urgency = pynotify.URGENCY_NORMAL
            self._cleanup_head = _("Warning: \'%s\' is getting full") % pool
            notifyBody = _("The file system: \'%s\', exceeded %s%% "
                           "of its total capacity") \
                            % (pool, threshhold)
            self._cleanup_body = _("\'%s\' exceeded %s%% of its total "
                     "capacity. To fix this, Time Slider has destroyed "
                     "some recent backups, and will destroy more as "
                     "capacity continues to diminish.\nTo prevent "
                     "this from happening again, delete any "
                     "unnecessary files on \'%s\', or add disk space "
                     "(see ZFS documentation).\n") \
                     % (pool, threshhold, pool)
        else:
            return # No other values currently supported

        if (self._note != None):
            self._note.close()
        self._note = pynotify.Notification(self._cleanup_head,
                                           notifyBody)
        self._note.add_action("clicked",
                              _("Details..."),
                              self._show_cleanup_details)
        self._note.connect("closed",
                           self._notification_closed)
        self._note.set_urgency(urgency)
        self._note.set_timeout(expiry)
        self._setup_icon_for_note()
        self._icon.set_blinking(True)
        gobject.idle_add(self._show_notification)

    def _connect_to_object(self):
        try:
            remote_object = bus.get_object("org.opensolaris.TimeSlider",
                                           "/org/opensolaris/TimeSlider/autosnap")
        except dbus.DBusException:
            print "Failed to connect to remote D-Bus object: %s" % \
                    ("/org/opensolaris/TimeSlider/autosnap")

        #Create an Interface wrapper for the remote object
        iface = dbus.Interface(remote_object, "org.opensolaris.TimeSlider.autosnap")

        iface.connect_to_signal("capacity_exceeded", self._cleanup_handler, sender_keyword='sender',
                                interface_keyword='interface', path_keyword='path')


bus = dbus.SystemBus()

def main(argv):
    mainloop = gobject.MainLoop()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default = True)
    gobject.threads_init()
    pynotify.init(_("Time Slider"))

    # Notification objects need to share common
    # status icon and popup menu so these are created
    # outside the object and passed to the constructor
    menu = gtk.Menu()
    icon = gtk.StatusIcon()
    icon.set_from_icon_name("time-slider-setup")
    cleanupNote = CleanupNote(icon, menu)
    rsyncNote = RsyncNote(icon, menu)

    try:
        mainloop.run()
    except:
        print "Exiting"

if __name__ == '__main__':
    main()


