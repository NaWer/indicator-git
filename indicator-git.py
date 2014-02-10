#!/usr/bin/python
# -*- coding: utf-8 -*-
### BEGIN LICENSE
# Copyright (c) 2014 Fournier Erwan
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
### END LICENSE
VERSION = '0.1'
import os, sys, threading, shutil
from subprocess import check_output, CalledProcessError, STDOUT, Popen
import re, time
from datetime import date
import gtk, gobject
import appindicator
import pynotify

import ConfigParser
from gettext import gettext as _
# Simple Traceback :
import traceback
def formatExceptionInfo(maxTBlevel=5):
	cla, exc, trbk = sys.exc_info()
	excName = cla.__name__
	try:
		excArgs = exc.__dict__["args"]
	except KeyError:
		excArgs = "<no args>"
	excTb = traceback.format_tb(trbk, maxTBlevel)
	return ("%s %s %s" % (excName, excArgs, excTb))


os.environ["LC_ALL"] = "C"

DIRECTORY_PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))
DIRECTORY_CONFIGURATION = '%s/.indicator-git' % os.environ["HOME"]
DIRECTORY_MIRRORS = os.path.join(DIRECTORY_CONFIGURATION, 'mirrors')
if not os.path.exists(DIRECTORY_MIRRORS):
	os.makedirs(DIRECTORY_MIRRORS)
FILE_CONFIGURATION = os.path.join(DIRECTORY_CONFIGURATION, 'config')

DEFAULT_INTERVAL = 1800 # seconds
DEFAULT_GIT_VIEWER = "/usr/bin/giggle";


class GitMonitor(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		self.lock = threading.Lock()
		self.indicator = appindicator.Indicator("indicator-git", "git", appindicator.CATEGORY_APPLICATION_STATUS)
		self.indicator.set_status(appindicator.STATUS_ACTIVE)

		self.repositories = {}
		self.read_config()

		self.initialize_menu()
		self.indicator.set_menu(self.menu['gtk'])

		self.pause = False

	def read_config(self):

		print 'Read configuration file'

		self.config = {"interval": DEFAULT_INTERVAL, "viewer": DEFAULT_GIT_VIEWER, "notification": {"commit": True, "branch": True, "tag": True}}
		try:
			conf = ConfigParser.SafeConfigParser()
			conf.read(FILE_CONFIGURATION)
			self.config["interval"]					= conf.getint("general", "interval")
			self.config["viewer"]					= conf.get("general", "viewer")
			self.config["notification"]["commit"]	= conf.getboolean("notification", "commit")
			self.config["notification"]["commit"]	= True
			self.config["notification"]["branch"]	= conf.getboolean("notification", "branch")
			self.config["notification"]["branch"]	= True
			self.config["notification"]["tag"]		= conf.getboolean("notification", "tag")
			self.config["notification"]["tag"]		= True
			self.repositories = map(lambda n:n[1],sorted(conf.items("repositories")))
		except:
			pass

	def initialize_menu(self):

		print 'Initializing menu'

		self.menu = {}
		self.menu['gtk'] = gtk.Menu()
		self.menu['items'] = {'repositories':{}}

		os.chdir(DIRECTORY_MIRRORS)
		for dirname in os.listdir(DIRECTORY_MIRRORS):
			if not os.path.isdir(dirname):
				continue
			repositoryName = os.path.splitext(dirname)[0]
			repo_item = gtk.MenuItem(repositoryName)
			self.menu['gtk'].append(repo_item)
			self.menu['items']['repositories'][repositoryName] = repo_item
			self.menu['items']['repositories'][repositoryName].connect("activate", self.viewer, dirname)
			# TODO count bubble

		self.menu['items']['clear'] = gtk.MenuItem("Clear")
		self.menu['items']['clear'].connect("activate", self.clear)
		self.menu['gtk'].append(self.menu['items']['clear'])

		self.menu['items']['sep_top'] = gtk.SeparatorMenuItem()
		self.menu['gtk'].append(self.menu['items']['sep_top'])


		self.menu['items']['status'] = gtk.MenuItem("Initializing")
		self.menu['items']['status'].set_sensitive(False)
		self.menu['items']['status'].show()
		self.menu['gtk'].append(self.menu['items']['status'])

		self.menu['items']['sep_middle'] = gtk.SeparatorMenuItem()
		self.menu['items']['sep_middle'].show()
		self.menu['gtk'].append(self.menu['items']['sep_middle'])

		self.menu['items']['refresh'] = gtk.MenuItem("Refresh")
		self.menu['items']['refresh'].connect("activate", self.update)
		self.menu['items']['refresh'].show()
		self.menu['gtk'].append(self.menu['items']['refresh'])

		self.menu['items']['pause'] = gtk.MenuItem("Pause fetching")
		self.menu['items']['pause'].connect("activate", self.toggle_fetching)
		self.menu['items']['pause'].show()
		self.menu['gtk'].append(self.menu['items']['pause'])

		self.menu['items']['sep_bottom'] = gtk.SeparatorMenuItem()
		self.menu['items']['sep_bottom'].show()
		self.menu['gtk'].append(self.menu['items']['sep_bottom'])

		self.menu['items']['prefs'] = gtk.MenuItem("Preferences...")
		self.menu['items']['prefs'].connect("activate", self.prefs)
		self.menu['items']['prefs'].show()
		self.menu['gtk'].append(self.menu['items']['prefs'])

		self.menu['items']['about'] = gtk.MenuItem("About")
		self.menu['items']['about'].connect("activate", self.about)
		self.menu['items']['about'].show()
		self.menu['gtk'].append(self.menu['items']['about'])

		self.menu['items']['quit'] = gtk.MenuItem("Quit")
		self.menu['items']['quit'].connect("activate", self.quit)
		self.menu['items']['quit'].show()
		self.menu['gtk'].append(self.menu['items']['quit'])

	def set_status_label(self, label):
		try:
			self.lock.acquire(True)
			self.menu['items']['status'].set_label(label)
		except Exception, e:
			traceback.format_exc(e)
		self.lock.release()

	def update(self, widget=None):
		threading.Thread(target=self.fetch, name='Fetcher').start()

	def fetch(self, widget=None):

		print "Fetching"

		self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/fetching.png"))
		self.set_status_label("Fetching")

		urls = []
		for dirname in os.listdir(DIRECTORY_MIRRORS):
			os.chdir(DIRECTORY_MIRRORS)
			if not os.path.isdir(dirname):
				continue
			os.chdir(dirname)

			# Get the remote origin url :
			try:
				url = check_output(["git", "config", "--get", "remote.origin.url"], stderr=STDOUT).rstrip()
				urls.append(url)
			except:
				print formatExceptionInfo()
				continue


			# Repository was deleted :
			if url not in self.repositories:
				os.chdir(DIRECTORY_MIRRORS)
				print "Deleting %s/%s" % (DIRECTORY_MIRRORS, dirname)
				self.menu['items']['status'].set_label("Deleting %s" % (dirname))
				shutil.rmtree(dirname)
				continue

			# Fetch the repository :
			repositoryName = os.path.splitext(dirname)[0]
			dirname = os.path.splitext(dirname)[0]
			print "Fetching %s/%s" % (DIRECTORY_MIRRORS, dirname)
			self.menu['items']['status'].set_label("Fetching %s" % (dirname))

			output = ''
			try:
				output = check_output(["git", "fetch"], stderr=STDOUT)
			except CalledProcessError:
				print "Error fetching %s" % dirname
				self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/error.png"))
				self.set_status_label("Error fetching %s" % dirname)
				pynotify.init("git-indicator")
				n = pynotify.Notification("Error fetching %s" % dirname, '', os.path.join(DIRECTORY_PROJECT_ROOT, "icons/error.png"))
				n.show()


			for line in output.split('\n'):
				if '->' not in line:
					continue
				if '..' in line:
					commit_range = line.split()[0]
					branch_name = line.split()[1]
					# TODO for each commits (split('\n') ???)
					commit_message = check_output(["git", "log", commit_range, "--pretty=format:%s"], stderr=STDOUT)
					commit_author = check_output(["git", "log", commit_range, "--pretty=format:%an"], stderr=STDOUT)
					print 'New commits in %s/%s by %s: %s' % (dirname, branch_name, commit_author, commit_message)
					self.menu['items']['clear'].show()
					self.menu['items']['sep_top'].show()
					self.menu['items']['repositories'][dirname].show()
					if self.indicator.get_icon() == os.path.join(DIRECTORY_PROJECT_ROOT, "icons/fetching.png"):
						self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/commit.png"))
					# TODO notify only if checked :
					pynotify.init("git-indicator")
					n = pynotify.Notification("New commits in %s/%s (%s)" % (dirname, branch_name, commit_author), commit_message, os.path.join(DIRECTORY_PROJECT_ROOT, "icons/commit.png"))
					n.show ()

				if 'new branch' in line:
					branch_name = line.split()[3]
					print 'New branch %s/%s' % (dirname, branch_name)
					self.menu['items']['clear'].show()
					self.menu['items']['sep_top'].show()
					self.menu['items']['repositories'][dirname].show()
					if self.indicator.get_icon() == os.path.join(DIRECTORY_PROJECT_ROOT, "icons/fetching.png"):
						self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/branch.png"))
					pynotify.init("git-indicator")
					n = pynotify.Notification("New branch %s/%s" % (dirname, branch_name), '', os.path.join(DIRECTORY_PROJECT_ROOT, "icons/branch.png"))
					n.show ()

				if 'new tag' in line:
					tag_name = line.split()[3]
					print 'New tag %s/%s' % (dirname, tag_name)
					self.menu['items']['clear'].show()
					self.menu['items']['sep_top'].show()
					self.menu['items']['repositories'][dirname].show()
					if self.indicator.get_icon() == os.path.join(DIRECTORY_PROJECT_ROOT, "icons/fetching.png"):
						self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/tag.png"))
					pynotify.init("git-indicator")
					n = pynotify.Notification("New tag %s/%s" % (dirname, tag_name), '', os.path.join(DIRECTORY_PROJECT_ROOT, "icons/tag.png"))
					n.show ()

		# Clone new repositories :
		os.chdir(DIRECTORY_MIRRORS)
		for url in self.repositories:
			if url not in urls:
				try:
					print "Cloning %s" % (url)
					self.menu['items']['status'].set_label("Cloning %s" % (url))
					output = check_output(["git", "clone", "--mirror", url], stderr=STDOUT)
				except CalledProcessError:
					print "Error cloning %s" % url
					print formatExceptionInfo()
					self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/error.png"))
					self.set_status_label("Error cloning %s" % url)
					pynotify.init("git-indicator")
					n = pynotify.Notification("Error cloning %s" % url, '', os.path.join(DIRECTORY_PROJECT_ROOT, "icons/error.png"))
					n.show()

		print "Done"
		self.set_status_label("Up to date")

		if self.indicator.get_icon() == os.path.join(DIRECTORY_PROJECT_ROOT, "icons/fetching.png"):
			if self.pause:
				self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/initializing.png"))
			else:
				self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/waiting.png"))
		if not self.pause:
			self.schedule_refresh()

	def clear(self, widget=None):
		self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/waiting.png"))
		self.menu['items']['clear'].hide()
		self.menu['items']['sep_top'].hide()
		for dirname in self.menu['items']['repositories']:
			self.menu['items']['repositories'][dirname].hide()

	def viewer(self, widget=None, dirname=None):
		if dirname:
			path = os.chdir(os.path.join(DIRECTORY_MIRRORS, dirname))
			Popen(DEFAULT_GIT_VIEWER)

	def schedule_refresh(self, widget=None, force_rate=False):
		if hasattr(self, "refresh_id"):
			gobject.source_remove(self.refresh_id)
		rate = DEFAULT_INTERVAL * 1000
		if force_rate:
			rate = force_rate
		print 'Scheduling %ds' % (rate/1000)
		self.refresh_rate = rate
		self.refresh_id = gobject.timeout_add(rate, self.update)

	def toggle_fetching(self, widget):
		self.pause = not self.pause
		if self.pause:
			print 'Disable scheduling'
			if hasattr(self, "refresh_id"):
				gobject.source_remove(self.refresh_id)
			self.menu['items']['pause'].set_label("Resume fetching")
			self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/initializing.png"))
		else:
			self.menu['items']['pause'].set_label("Pause fetching")
			self.indicator.set_icon(os.path.join(DIRECTORY_PROJECT_ROOT, "icons/waiting.png"))
			self.update()

	def prefs(self, widget):
		if ((not hasattr(self, 'prefswindow')) or (not self.prefswindow.get_visible())):
			self.prefswindow = PreferencesDialog()
			self.prefswindow.show()

	def about(self, widget):
		self.aboutDialog = gtk.AboutDialog()
		# Title :
		logo_path = os.path.join(DIRECTORY_PROJECT_ROOT, "icons/commit.png")
		self.aboutDialog.set_logo(gtk.gdk.pixbuf_new_from_file(logo_path))
		self.aboutDialog.set_name("Indicator Git")
		# Version :
		self.aboutDialog.set_version(VERSION)
		# Authors :
		self.aboutDialog.set_authors(['Erwan Fournier <mail@erwan.me>', '', 'Thanks to', '\tIsrael Tsadok (https://github.com/itsadok/git-indicator)', '\tMarcin Kulik (https://github.com/sickill/git-dude'])
		# Description :
		self.aboutDialog.set_comments('A simple indicator with notification for git repositories')
		# Licence :
		self.aboutDialog.set_copyright('Copyright %d Erwan Fournier' % date.today().year)
		self.aboutDialog.set_wrap_license(True)
		ifile = open(os.path.join(DIRECTORY_PROJECT_ROOT, "LICENSE.txt"), "r")
		self.aboutDialog.set_license(ifile.read().replace('\x0c', ''))
		ifile.close()
		self.aboutDialog.set_website("https://github.com/NaWer/indicator-git")
		self.aboutDialog.connect("response", self.about_close)
		self.aboutDialog.show()
	def about_close(self, widget, event=None):
		self.aboutDialog.destroy()

	def quit(self, widget=None):
		gtk.main_quit()
		sys.exit(0)

class PreferencesDialog(gtk.Dialog):
	""" Class for preferences dialog """
	__gtype_name__ = "PreferencesDialog"

	def __new__(cls):
		builder = gtk.Builder()
		builder.set_translation_domain('indicator-git')
		builder.add_from_file(os.path.join(DIRECTORY_PROJECT_ROOT, 'PreferencesDialog.ui'))
		new_object = builder.get_object("preferences_dialog")
		new_object.finish_initializing(builder)
		return new_object

	def finish_initializing(self, builder):
		self.builder = builder
		self.builder.get_object('rate').set_value(indicator.config['interval'])
		self.builder.get_object('notifcommit').set_active(indicator.config['notification']['commit'])
		self.builder.get_object('notifbranch').set_active(indicator.config['notification']['branch'])
		self.builder.get_object('notiftag').set_active(indicator.config['notification']['tag'])
		for repository in indicator.repositories:
			self.builder.get_object('repositorieslist').append([repository])
		self.builder.connect_signals(self)

	def on_remove_repository(self, widget):
		selection = self.builder.get_object('repositories_list').get_selection()
		model, iter = selection.get_selected()
		if iter != None:
			model.remove(iter)
		self.builder.get_object('ok_button').set_sensitive(True)

	def on_add_repository(self, widget):
		if ((not hasattr(self, 'add_repository_dialog')) or (not self.add_repository_dialog.get_visible())):
			self.add_repository_dialog = AddRepositoryDialog()
			self.add_repository_dialog.show()

	def cancel(self, widget, data=None):
		self.destroy()

	def change(self,widget):
		self.builder.get_object('ok_button').set_sensitive(True)

	def ok(self, widget, data=None):
		interval	= str(int(self.builder.get_object('rate').get_value()))
		notifcommit	= str(self.builder.get_object('notifcommit').get_active())
		notifbranch	= str(self.builder.get_object('notifbranch').get_active())
		notiftag	= str(self.builder.get_object('notiftag').get_active())

		conf = ConfigParser.SafeConfigParser()
		conf.read(FILE_CONFIGURATION)
		f = open(FILE_CONFIGURATION, 'w')

		conf.set('general', 'interval', interval)

		conf.set('notification', 'commit', notifcommit)
		conf.set('notification', 'branch', notifbranch)
		conf.set('notification', 'tag', notiftag)

		for index, repository in enumerate(self.builder.get_object('repositories_list').get_model()):
			conf.set('repositories', str(index), repository[0])

		conf.write(f)
		f.close()
		self.destroy()

class AddRepositoryDialog(gtk.Dialog):
	""" Class for add a new repository in repository list """
	__gtype_name__ = "AddRepositoryDialog"

	def __new__(cls):
		builder = gtk.Builder()
		builder.set_translation_domain('indicator-git')
		builder.add_from_file(os.path.join(DIRECTORY_PROJECT_ROOT, 'AddRepositoryDialog.ui'))
		new_object = builder.get_object("add_repository_dialog")
		new_object.finish_initializing(builder)
		return new_object

	def finish_initializing(self, builder):
		self.builder = builder
		self.builder.connect_signals(self)

	def cancel(self,widget):
		self.destroy()

	def change(self,widget):
		self.builder.get_object('add_button').set_sensitive(True)

	def add(self,widget):
		repository = self.builder.get_object('location').get_text()
		if repository:
			indicator.prefswindow.builder.get_object('repositorieslist').append([repository])
			indicator.prefswindow.builder.get_object('ok_button').set_sensitive(True)
		self.destroy()

def main():
	gtk.main()
	return 0

if __name__ == "__main__":
	gtk.gdk.threads_init()
	gtk.gdk.threads_enter()
	indicator = GitMonitor()
	indicator.schedule_refresh(force_rate=1)
	main()
	gtk.gdk.threads_leave()
