include VERSION

mkinstalldirs = /usr/bin/mkdir -p
INSTALL = /usr/sbin/install
INSTALL_DATA = ${INSTALL} -u root -g bin -m 644 -f
INSTALL_PROGRAM = ${INSTALL} -u root -g bin -f
INSTALL_SCRIPT = ${INSTALL} -f
RM = /usr/bin/rm -f
RMRF = /usr/bin/rm -Rf
RMDIR = /usr/bin/rmdir
SUBDIRS = po data

DISTFILES = Authors \
			VERSION \
			ChangeLog \
			Makefile \
			py-compile.py \
			$(SUBDIRS) \
			lib \
			usr \
			var \

all: compile
	for subdir in $(SUBDIRS); do \
	  cd $$subdir; make; cd ..;\
	done
	echo $(VERSION)

compile:
	python py-compile.py

dist: all
	$(RMRF) time-slider-$(VERSION)
	mkdir time-slider-$(VERSION)
	cp -pR $(DISTFILES) time-slider-$(VERSION)
	/usr/bin/tar cf - time-slider-$(VERSION) | bzip2 > time-slider-$(VERSION).tar.bz2
	$(RMRF) time-slider-$(VERSION)

install:
	for subdir in $(SUBDIRS); do \
	  cd $$subdir; \
	  make DESTDIR=$(DESTDIR) GETTEXT_PACKAGE=time-slider install; \
	  cd ..;\
	done
	$(mkinstalldirs) $(DESTDIR)/lib/svc/method
	$(INSTALL_SCRIPT) $(DESTDIR)/lib/svc/method lib/svc/method/time-slider
	$(mkinstalldirs) $(DESTDIR)/usr/bin
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/bin usr/bin/time-slider-setup
	$(mkinstalldirs) $(DESTDIR)/usr/lib
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/lib usr/lib/time-slider-cleanup
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/lib usr/lib/time-slider-delete
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/lib usr/lib/time-slider-notify
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/lib usr/lib/time-slider-snapshot
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/16x16/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/16x16/apps usr/share/icons/hicolor/16x16/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/24x24/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/24x24/apps usr/share/icons/hicolor/24x24/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/32x32/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/32x32/apps usr/share/icons/hicolor/32x32/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/36x36/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/36x36/apps usr/share/icons/hicolor/36x36/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/48x48/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/48x48/apps usr/share/icons/hicolor/48x48/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/72x72/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/72x72/apps usr/share/icons/hicolor/72x72/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/icons/hicolor/96x96/apps
	$(INSTALL_DATA) $(DESTDIR)/usr/share/icons/hicolor/96x96/apps usr/share/icons/hicolor/96x96/apps/time-slider-setup.png
	$(mkinstalldirs) $(DESTDIR)/usr/share/time-slider/glade
	$(INSTALL_DATA) $(DESTDIR)/usr/share/time-slider/glade usr/share/time-slider/glade/time-slider-delete.glade
	$(INSTALL_DATA) $(DESTDIR)/usr/share/time-slider/glade usr/share/time-slider/glade/time-slider-setup.glade
	$(INSTALL_DATA) $(DESTDIR)/usr/share/time-slider/glade usr/share/time-slider/glade/time-slider-snapshot.glade
	$(mkinstalldirs) $(DESTDIR)/usr/share/time-slider/lib/time_slider
	for file in usr/share/time-slider/lib/time_slider/*.py; do \
		if test -f $$file ; then \
		  $(INSTALL_DATA) $(DESTDIR)/usr/share/time-slider/lib/time_slider $$file; \
		fi; \
	done
	for file in usr/share/time-slider/lib/time_slider/*.pyc; do \
		if test -f $$file ; then \
		  $(INSTALL_DATA) $(DESTDIR)/usr/share/time-slider/lib/time_slider $$file; \
		fi; \
	done
	$(mkinstalldirs) $(DESTDIR)/var/svc/manifest/application
	$(INSTALL_DATA) $(DESTDIR)/var/svc/manifest/application var/svc/manifest/application/time-slider.xml
	
uninstall:
	for subdir in $(SUBDIRS); do \
	  cd $$subdir; \
	  make DESTDIR=$(DESTDIR) GETTEXT_PACKAGE=time-slider uninstall; \
	  cd ..;\
	done
	$(RM) $(DESTDIR)/lib/svc/method/time-slider
	$(RM) $(DESTDIR)/usr/bin/time-slider-setup
	$(RM) $(DESTDIR)/usr/lib/time-slider-cleanup
	$(RM) $(DESTDIR)/usr/lib/time-slider-delete
	$(RM) $(DESTDIR)/usr/lib/time-slider-notify
	$(RM) $(DESTDIR)/usr/lib/time-slider-snapshot
	$(RM) $(DESTDIR)/usr/share/icons/hicolor/*/apps/time-slider-setup.png
	$(RMRF) $(DESTDIR)/usr/share/time-slider
	$(RM) $(DESTDIR)/var/svc/manifest/application/time-slider.xml
