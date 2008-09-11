
mkinstalldirs = /usr/bin/mkdir -p
INSTALL = /usr/sbin/install
INSTALL_DATA = ${INSTALL} -u root -g bin -m 644 -f
INSTALL_PROGRAM = ${INSTALL} -u root -g bin -f
INSTALL_SCRIPT = ${INSTALL} -f
RM = /usr/bin/rm -f
RMRF = /usr/bin/rm -Rf
RMDIR = /usr/bin/rmdir

all:

install:
	$(mkinstalldirs) $(DESTDIR)/lib/svc/method
	$(INSTALL_SCRIPT) $(DESTDIR)/lib/svc/method lib/svc/method/time-slider
	$(mkinstalldirs) $(DESTDIR)/usr/bin
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/bin usr/bin/time-slider-setup
	$(mkinstalldirs) $(DESTDIR)/usr/lib
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/lib usr/lib/time-slider-cleanup
	$(INSTALL_PROGRAM) $(DESTDIR)/usr/lib usr/lib/time-slider-notify
	$(mkinstalldirs) $(DESTDIR)/usr/share/applications
	$(INSTALL_DATA) $(DESTDIR)/usr/share/applications usr/share/applications/time-slider-setup.desktop
	$(mkinstalldirs) $(DESTDIR)/usr/share/time-slider/glade
	$(INSTALL_DATA) $(DESTDIR)/usr/share/time-slider/glade usr/share/time-slider/glade/time-slider-setup.glade
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
	$(RM) $(DESTDIR)/lib/svc/method/time-slider
	$(RM) $(DESTDIR)/usr/bin/time-slider-setup
	$(RM) $(DESTDIR)/usr/lib/time-slider-cleanup
	$(RM) $(DESTDIR)/usr/lib/time-slider-notify
	$(RM) $(DESTDIR)/usr/share/applications/time-slider-setup.desktop
	$(RMRF) $(DESTDIR)/usr/share/time-slider
	$(RM) $(DESTDIR)/var/svc/manifest/application/time-slider.xml
