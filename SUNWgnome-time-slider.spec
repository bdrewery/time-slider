#
# spec file for package SUNWtime-slider
#
# includes module(s): time-slider
#
# Copyright 2008 Sun Microsystems, Inc.
# This file and all modifications and additions to the pristine
# package are under the same license as the package itself.
#
# Owner: Niall Power
#
%include Solaris.inc

Name:                    SUNWgnome-time-slider
Summary:                 Time Slider ZFS snapshot management for GNOME
Version:                 0.1.0
Source:                  time-slider.tar.bz2
SUNW_BaseDir:            %{_basedir}
SUNW_Copyright:          %{name}.copyright
BuildRoot:               %{_tmppath}/%{name}-%{version}-build

%include default-depend.inc
BuildRequires:           SUNWgnome-python-libs-devel
BuildRequires:           SUNWgksu-devel
Requires:                SUNWPython
Requires:                SUNWgnome-python-libs
Requires:                SUNWgksu
Requires:                SUNWzfs-auto-snapshot
Requires:                %{name}-root

%package root
Summary:                 %{summary} - / filesystem
SUNW_BaseDir:            /
%include default-depend.inc

%prep
%setup -q -n time-slider

%build
make

%install
rm -rf $RPM_BUILD_ROOT
make install DESTDIR=$RPM_BUILD_ROOT

%{?pkgbuild_postprocess: %pkgbuild_postprocess -v -c "%{version}:%{jds_version}:%{name}:$RPM_ARCH:%(date +%%Y-%%m-%%d):%{support_level}" $RPM_BUILD_ROOT}

%clean
rm -rf $RPM_BUILD_ROOT

%if %(test -f /usr/sadm/install/scripts/i.manifest && echo 0 || echo 1)
%iclass manifest -f i.manifest
%endif

%pre root
#!/bin/sh
#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
#

# Presence of this temp file will tell postinstall script
# that the time-slider service is already installed, in which case
# the current service state will be preserved, be it enabled
# or disabled.
rm -f $PKG_INSTALL_ROOT/var/time-slider_installed.tmp > /dev/null 2>&1

if [ -f $PKG_INSTALL_ROOT/var/svc/manifest/application/time-slider.xml ]; then 
	touch $PKG_INSTALL_ROOT/var/time-slider_installed.tmp
fi

exit 0

%post
%include icon-cache.script

%post root
#!/bin/sh
#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
#

# Preinstall script will create this file if time-slider service was 
# already installed, in which case we preserve current service state,
# be it enabled or disabled.
if [ -f $PKG_INSTALL_ROOT/var/time-slider_installed.tmp ]; then
	rm -f $PKG_INSTALL_ROOT/var/time-slider_installed.tmp
else
	# enable time-slider:
	# - PKG_INSTALL_ROOT is / or empty when installing onto a live system
	#   and we can invoke svcadm directly;
	# - otherwise it's upgrade, so we append to the upgrade script
	if [ "${PKG_INSTALL_ROOT:-/}" = "/" ]; then
		if [ `/sbin/zonename` = global ]; then
			/usr/sbin/svcadm enable -r svc:/application/time-slider:default
		fi
	else
		cat >> ${PKG_INSTALL_ROOT}/var/svc/profile/upgrade <<-EOF
		if [ \`/sbin/zonename\` = global ]; then
			/usr/sbin/svcadm enable -r svc:/application/time-slider:default
		fi
EOF
	fi
fi

exit 0

%files
%defattr (-, root, bin)
%{_bindir}/*
%dir %attr (0755, root, bin) %{_libdir}
%{_libdir}/time-slider-*
%dir %attr (0755, root, sys) %{_datadir}
%dir %attr (0755, root, other) %{_datadir}/applications
%{_datadir}/applications/time-slider-*.desktop
%{_datadir}/icons/hicolor/*/apps/time-slider-setup.png
%{_datadir}/time-slider/*

%files root
%defattr (-, root, bin)
%dir %attr (0755, root, sys) /var
%dir %attr (0755, root, sys) /var/svc
%dir %attr (0755, root, sys) /var/svc/manifest
%dir %attr (0755, root, sys) /var/svc/manifest/application
%class(manifest) %attr (0444, root, sys) /var/svc/manifest/application/time-slider.xml
%attr (0555, root, bin) /lib/svc/method/time-slider

%changelog
* Wed Sep 17 2008 - niall.power@sun.com
- Initial spec file created.

