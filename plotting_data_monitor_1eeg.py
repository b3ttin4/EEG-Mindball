""" 
A simple demonstration of a serial port monitor that plots live
data using pyqtgraph.
The monitor expects to receive 8-byte data packets on the 
serial port. The packages are decoded such that the first byte
contains the 3 most significant bits and the second byte contains
the 7 least significat bits.
"""
import random, sys
import numpy as np
from PyQt4.QtCore import *
from PyQt4.QtGui import *
import pyqtgraph as pg
import Queue

from com_monitor import ComMonitorThread
from libs.utils import get_all_from_queue, get_item_from_queue
from libs.decode import decode_output
from libs.read_audio import play_sound
from livedatafeed import LiveDataFeed

from scipy.interpolate import interp1d
from scipy.signal import butter, lfilter


color1 = "limegreen"
width_signal = 5
time_axis_range = 2 ## in s

pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')
#fixes to white background and black labels

sound_path = '/home/bettina/physics/arduino/eeg_mindball/sound/'
sound_files = ['End_of_football_game','Football-crowd-GOAL','intro_brass_01','Jingle_Win_00','Jingle_Win_01']
ambience_sound = sound_path + 'Norwegian_football_matchsoccer_game_ambience.wav'

class PlottingDataMonitor(QMainWindow):
	def __init__(self, parent=None):
		super(PlottingDataMonitor, self).__init__(parent)
		
		self.monitor_active = False
		self.com_monitor = None
		self.livefeed = LiveDataFeed()
		self.temperature_samples = []
		self.timer = QTimer()
		
		self.create_menu()
		self.create_main_frame()
		self.create_status_bar()
		
		## spectrum boundaries
		self.x_low = 4
		self.x_high = 13
		self.frequency = 1 ##Hz
		self.nmax = 1000
		self.fft1_norm = np.zeros((self.nmax//2))
		self.b, self.a = butter(3, [0.0, 0.34], btype='band')
		
		## init arena stuff
		self.ball_coordx = 0.
		self.ball_coordy = 0.
		self.tuning_factor = 0.1
		self.text_html = '<div style="text-align: center"><span style="color: #FFF; font-size: 30pt">Goal</span><br><span style="color: #FFF; font-size: 30pt; text-align: center"> {} is winner </span></div>'
		self.show_one_item = False
		self.winner_text = None
		self.playing = False
		self.win_hymn_no = 2
		
	
	def create_plot(self, xlabel, ylabel, xlim, ylim, ncurves=1):
		plot = pg.PlotWidget()
		curve = plot.plot(antialias=True)
		curve.setPen((200,200,100))
		plot.setLabel('left', ylabel)
		plot.setLabel('bottom', xlabel)
		plot.setXRange(xlim[0], xlim[1])
		plot.setYRange(ylim[0], ylim[1])

		#plot.setCanvasBackground(Qt.black)
		plot.replot()
		
		pen = QPen(QColor(color1))
		#pen.setWidth(0.9)
		curve.setPen(pen)
		
		if ncurves==2:
			curve2 = plot.plot(antialias=True)
			#pen.setWidth(0.9)
			pen2 = QPen(QColor('magenta'))
			curve2.setPen(pen2)
			return plot, curve, curve2
		else:
			return plot, curve
	
	def create_arenaplot(self, xlabel, ylabel="Player "+color1, xlim=[-1,1], ylim=[-1,1], curve_style=None):
		""" create plot/arena in form of a soccer field
		"""

		plot = pg.PlotWidget(background=QColor("#217300"))
		
		if curve_style is not None:
			curve = plot.plot(symbol=curve_style, antialias=True, symbolSize=15, symbolBrush='w')
		else:
			curve = plot.plot(antialias=True)
		plot.setLabel('left', ylabel)
		plot.setLabel('bottom', xlabel)
		plot.setXRange(xlim[0], xlim[1], 0.1)
		plot.setYRange(ylim[0], ylim[1], 0.1)
		plot.hideAxis('bottom')
		plot.hideAxis('left')
		plot.replot()
		
		spi = pg.ScatterPlotItem(size=5, pen=pg.mkPen(None), brush=pg.mkBrush(255,255,255,255))
		spi.addPoints([{'pos' : [0,0], 'data' : 1}])
		plot.addItem(spi)
		
		spi = pg.ScatterPlotItem(size=70, brush=pg.mkBrush(255,255,255,0))
		spi.addPoints([{'pos' : [0,0], 'data' : 1, 'pen' : 'w'}])
		plot.addItem(spi)
		
		central_line = pg.GraphItem()
		plot.addItem(central_line)
		w = 0.5
		pos = np.array([[0.,-1.],[0.,1.],[-1.,w],[-0.7,w],[-0.7,-w],
		[-1.,-w],[1,w],[0.7,w],[0.7,-w],[1,-w], [-1,-1],[-1,1], [1,-1],[1,1],
		[-1,0.2],[-1.1,0.2],[-1.1,-0.2],[-1,-0.2],
		[1,0.2],[1.1,0.2],[1.1,-0.2],[1,-0.2]])
		adj = np.array([[0,1], [2,3],[3,4],[4,5], [6,7],[7,8],[8,9],[10,12],[11,13],
		[14,15],[15,16],[16,17],[18,19],[19,20],[20,21], [10,11],[12,13]])
		lines = np.array([(255,255,255,255,1)]*15 + [(255,0,255,255,4),(0,255,0,255,4)],
		dtype=[('red',np.ubyte),('green',np.ubyte),('blue',np.ubyte),('alpha',np.ubyte),('width',float)])
		central_line.setData(pos=pos,adj=adj,pen=lines,size=0.1)
		
		return plot, curve
	
	def create_status_bar(self):
		self.status_text = QLabel('Monitor idle')
		self.statusBar().addWidget(self.status_text, 1)

	def create_main_frame(self):
		# Main frame and layout
		#
		self.mdi = QMdiArea()
		#self.main_frame = QWidget()
		#main_layout = QGridLayout()
		#main_layout.setColumnStretch(0,1)

		## Plot
		##
		self.plot, self.curve = self.create_plot('Time', 'Signal', [0,5], [0,1000])
		self.plot_fft, self.curve_fft = self.create_plot('Frequency', 'FFt', [0,60], [0,.01])

		plot_layout = QVBoxLayout()
		plot_layout.addWidget(self.plot)
		plot_layout.addWidget(self.plot_fft)
		
		plot_groupbox = QGroupBox('Signal')
		plot_groupbox.setLayout(plot_layout)
		
		### Arena
		###
		self.plot_arena, self.curve_arena = self.create_arenaplot(' ', 'Y', [-1,1,0], [-1,1,0], curve_style='o')
		
		plot_layout_arena = QHBoxLayout()
		plot_layout_arena.addWidget(self.plot_arena)
		
		plot_groupbox_arena = QGroupBox('Arena')
		plot_groupbox_arena.setLayout(plot_layout_arena)

		## Main frame and layout
		##
		self.mdi.addSubWindow(plot_groupbox)
		self.mdi.addSubWindow(plot_groupbox_arena)
		self.setCentralWidget(self.mdi)
		#main_layout.addWidget(plot_groupbox,0,0)
		#main_layout.addWidget(plot_groupbox_arena,0,1,1,1)
		
		#self.main_frame.setLayout(main_layout)
		#self.setGeometry(30, 30, 950, 500)
		
		#self.setCentralWidget(self.main_frame)


	def create_menu(self):
		self.file_menu = self.menuBar().addMenu("&File")

		self.start_action = self.create_action("&Start monitor",
			shortcut="Ctrl+M", slot=self.on_start, tip="Start the data monitor")
		self.stop_action = self.create_action("&Stop monitor",
			shortcut="Ctrl+T", slot=self.on_stop, tip="Stop the data monitor")
		self.start_arena_action = self.create_action("&Start arena",
			shortcut="Ctrl+A", slot=self.on_arena, tip="Start the arena")
		self.tiled = self.create_action("&Tile windows",
			shortcut="Ctrl+R", slot=self.tile_windows, tip="Tile open windows")
		exit_action = self.create_action("E&xit", slot=self.close, 
			shortcut="Ctrl+X", tip="Exit the application")
		
		self.start_action.setEnabled(True)
		self.stop_action.setEnabled(False)
		self.start_arena_action.setEnabled(False)
		
		self.add_actions(self.file_menu, 
			(   self.start_action, self.stop_action,
				self.start_arena_action, self.tiled,
				None, exit_action))
			
		self.help_menu = self.menuBar().addMenu("&Help")
		about_action = self.create_action("&About", 
			shortcut='F1', slot=self.on_about, 
			tip='About the monitor')
		
		self.add_actions(self.help_menu, (about_action,))

	def set_actions_enable_state(self):
		start_enable = not self.monitor_active
		stop_enable = self.monitor_active
		start_arena_enable = self.monitor_active
		
		self.start_action.setEnabled(start_enable)
		self.stop_action.setEnabled(stop_enable)
		self.start_arena_action.setEnabled(start_arena_enable)

	def on_about(self):
		msg = __doc__
		QMessageBox.about(self, "About the demo", msg.strip())
	
	def on_stop(self):
		""" Stop the monitor
		"""
		if self.com_monitor is not None:
			self.com_monitor.join(0.01)
			self.com_monitor = None

		self.monitor_active = False
		self.timer.stop()
		self.set_actions_enable_state()
		
		self.status_text.setText('Monitor idle')
	
	def reset_arena(self):
		"""bring ball back to center, remove winner sign"""
		#self.plot_arena.clear()
		self.plot_arena.removeItem(self.winner_text)
		self.show_one_item = False
		
		self.ball_coordx, self.ball_coordy = 0,0
		self.curve_arena.setData([self.ball_coordx], [self.ball_coordy])
	
	def reset_signal(self):
		""" empty list of signal values"""
		self.livefeed.updated_list = False
		self.livefeed.list_data = []
		self.curve.setData([], [])
		self.curve_fft.setData([], [])
		self.plot.replot()
		
	
	def on_start(self):
		""" Start the monitor: com_monitor thread and the update
			timer
		"""
		if self.com_monitor is not None:
			return
		
		if self.show_one_item is True:
			self.reset_arena()
			self.reset_signal()
		
		self.data_q = Queue.Queue()
		self.error_q = Queue.Queue()
		self.com_monitor = ComMonitorThread(
			self.data_q,
			self.error_q,
			'/dev/ttyACM0',
			230400)
			#115200)
		self.com_monitor.start()
		
		com_error = get_item_from_queue(self.error_q)
		if com_error is not None:
			QMessageBox.critical(self, 'ComMonitorThread error',
				com_error)
			self.com_monitor = None

		self.monitor_active = True
		self.set_actions_enable_state()
		
		self.timer = QTimer()
		self.connect(self.timer, SIGNAL('timeout()'), self.on_timer)
		update_freq = 1000. #Hz
		
		self.timer_plot = QTimer()
		self.connect(self.timer_plot, SIGNAL('timeout()'), self.on_timer_plot)
		update_freq_plot = 10. #Hz
		
		self.timer.start(1000.0 / update_freq) #ms
		self.timer_plot.start(1000.0 / update_freq_plot) #ms
		
		self.status_text.setText('Monitor running')
		
	def on_timer(self):
		""" Executed periodically when the monitor update timer
			is fired.
		"""
		self.read_serial_data()
		if self.livefeed.has_new_data:
			self.livefeed.append_data(self.livefeed.read_data())
			#self.livefeed.append_data_array(self.livefeed.read_data())
	
	def on_timer_plot(self):
		""" Executed periodically when the plot update timer
			is fired.
		"""
		self.update_monitor()
	
	def on_arena(self):
		self.playing = True
		self.ball_coordx, self.ball_coordy = 0,0
		self.curve_arena.setData([self.ball_coordx], [self.ball_coordy])
		print('Game is starting.')
	
	def tile_windows(self):
		self.mdi.tileSubWindows()
	
	def update_monitor(self):
		""" Updates the state of the monitor window with new 
			data. The livefeed is used to find out whether new
			data was received since the last update. If not, 
			nothing is updated.
		"""
		update1 = False
		if self.livefeed.updated_list:
			self.temperature_samples = self.livefeed.read_list()
			
			xdata = [s[0] for s in self.temperature_samples]
			ydata = [s[1] for s in self.temperature_samples]
			
			## interpolate signal
			n = len(ydata)
			f = interp1d(xdata, ydata)# alternative (slow) choice: kind='cubic'
			xdata = np.linspace(xdata[0],xdata[-1],n)
			ydata = f(xdata)

			## bandpass filter signal
			ydata = lfilter(self.b, self.a, ydata)
			
			self.plot.setXRange(max(0,xdata[-1]-time_axis_range), max(time_axis_range, xdata[-1]))
			self.curve.setData(xdata, ydata, _CallSync='off')
			
			# plot fft of port 1
			#
			if n>=(self.nmax):
				delta = xdata[1]-xdata[0]
				yfft = np.fft.rfft(ydata)
				x = np.fft.rfftfreq(n,d=delta)
				fft1 = np.abs(yfft)
				self.fft1_norm += fft1[1:]/np.sum(fft1[1:])		#single items not well weighted
				self.fft1_norm = self.fft1_norm/np.sum(self.fft1_norm)
			
				self.curve_fft.setData(x[1:],self.fft1_norm)
				
			if (self.playing and n>=(self.nmax)):
				ind_alpha = (x[1:]>self.x_low)*(x[1:]<self.x_high)
				power_alpha = np.sum(self.fft1_norm[ind_alpha])
			
				self.ball_coordx += (power_alpha)*self.tuning_factor
				self.ball_coordy += np.random.normal(scale=0.05)

				self.curve_arena.setData([np.sign(self.ball_coordx)*min(1, abs(self.ball_coordx))], [self.ball_coordy], _CallSync='off')

				if abs(self.ball_coordy)>(0.7*(1.1-abs(self.ball_coordx))):
					self.ball_coordy = self.ball_coordy*0.6
				if (abs(self.ball_coordx)>1 and self.show_one_item is False):
					winner_color = color1
					self.winner_text = pg.TextItem(html=self.text_html.format(winner_color), anchor=(0.5,2.3),\
					border=QColor(winner_color), fill=(201, 165, 255, 100))
					
					self.plot_arena.addItem(self.winner_text)
					self.show_one_item = True
					self.playing = False
					self.on_stop()
					self.win_hymn_no = np.random.randint(len(sound_files))
					play_sound(sound_path + sound_files[self.win_hymn_no] + '.wav')
					
	
	def read_serial_data(self):
		""" Called periodically by the update timer to read data
			from the serial port.
		"""
		qdata = list(get_all_from_queue(self.data_q))
		if len(qdata) > 0:
			output = decode_output(qdata[-1][0])
			data = dict(timestamp=qdata[-1][1], 
						temperature=float(np.nanmean(output)))
			self.livefeed.add_data(data)
			
		## dont average over signal but plot every bit, assume sample rate of 10kHz 
		#
		#qdata = list(get_all_from_queue(self.data_q))
		#if len(qdata) > 0:
			#output = decode_output(qdata[-1][0])
			#tstamp = qdata[-1][1]
			#tstamps = np.linspace(tstamp-len(output)*10**(-5),tstamp,len(output))
			#data = dict(timestamp=tstamps, 
						#temperature= np.array([float(item) for item in output]) )
			#self.livefeed.add_data(data)
		
		
		#qdata = list(get_item_from_queue(self.data_q))
		#tstamp = qdata[1]
		#output = decode_output(qdata[0])
		#if len(output) > 0:
			#data = dict(timestamp=tstamp, 
						#temperature=float(np.nanmean(output)))#
			#self.livefeed.add_data(data)
		
		#if len(output) > 0:
			#tstamps = np.linspace(tstamp-len(output)*10**(-5),tstamp,len(output))
			#data = dict(timestamp=tstamps, 
						#temperature= np.array([float(item) for item in output]) )
			#self.livefeed.add_data(data)
			
	# The following two methods are utilities for simpler creation
	# and assignment of actions
	#
	def add_actions(self, target, actions):
		for action in actions:
			if action is None:
				target.addSeparator()
			else:
				target.addAction(action)

	def create_action(  self, text, slot=None, shortcut=None, 
						icon=None, tip=None, checkable=False, 
						signal="triggered()"):
		action = QAction(text, self)
		if icon is not None:
			action.setIcon(QIcon(":/%s.png" % icon))
		if shortcut is not None:
			action.setShortcut(shortcut)
		if tip is not None:
			action.setToolTip(tip)
			action.setStatusTip(tip)
		if slot is not None:
			self.connect(action, SIGNAL(signal), slot)
		if checkable:
			action.setCheckable(True)
		return action


def main():
	app = QApplication(sys.argv)
	form = PlottingDataMonitor()
	form.show()	
	app.exec_()


if __name__ == "__main__":
	main()
