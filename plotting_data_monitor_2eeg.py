""" 
A simple demonstration of a serial port monitor that plots live
data using pyqtgraph.
The monitor expects to receive 8-byte data packets on the 
serial port. The packages are decoded such that the first byte
contains the 3 most significant bits and the second byte contains
the 7 least significat bits.
"""
import numpy as np
import random, sys
from PyQt4.QtCore import *
from PyQt4.QtGui import *
import pyqtgraph as pg
import Queue

from com_monitor import ComMonitorThread
#from eblib.serialutils import full_port_name, enumerate_serial_ports
from libs.utils import get_all_from_queue, get_item_from_queue
from libs.decode import decode_output
from livedatafeed import LiveDataFeed


class PlottingDataMonitor(QMainWindow):
	def __init__(self, parent=None):
		super(PlottingDataMonitor, self).__init__(parent)
		
		self.monitor_active = False
		self.com_monitor = None
		self.com_monitor2 = None
		self.livefeed = LiveDataFeed()
		self.livefeed2 = LiveDataFeed()
		self.temperature_samples = []
		self.temperature_samples2 = []
		self.timer = QTimer()
		
		self.create_menu()
		self.create_main_frame()
		self.create_status_bar()
		
		self.x_low = 0.1
		self.x_high = 3
		
		self.ball_coordx = [0.]
		self.ball_coordy = [0.]
		self.tuning_factor = 1.
		self.text_html = '<div style="text-align: center"><span style="color: #FFF; font-size: 40pt">Goal</span><br><span style="color: #FFF; font-size: 40pt; text-align: center"> {} is winner </span></div>'
		self.show_one_item = False
	
	def create_plot(self, xlabel, ylabel, xlim, ylim, curve_style=None, ncurves=1):
		plot = pg.PlotWidget()
		if curve_style is not None:
			curve = plot.plot(symbol=curve_style,antialias=True, symbolSize=15)
			#brush = QBrush(QColor('limegreen'))
			#curve.setBrush(brush)
		else:
			curve = plot.plot(antialias=True)
		plot.setLabel('left', ylabel)
		plot.setLabel('bottom', xlabel)
		plot.setXRange(xlim[0], xlim[1])
		plot.setYRange(ylim[0], ylim[1])

		#plot.setCanvasBackground(Qt.black)
		plot.replot()
		
		pen = QPen(QColor('limegreen'))
		#pen.setWidth(0.9)
		curve.setPen(pen)
		
		if ncurves==2:
			curve2 = plot.plot(symbol=curve_style)
			#pen.setWidth(0.9)
			pen2 = QPen(QColor('magenta'))
			curve2.setPen(pen2)
			return plot, curve, curve2
		else:
			return plot, curve

	def create_status_bar(self):
		self.status_text = QLabel('Monitor idle')
		self.statusBar().addWidget(self.status_text, 1)

	def create_main_frame(self):
		# Main frame and layout
		#
		self.main_frame = QWidget()
		main_layout = QGridLayout()
		#main_layout.setSpacing(3)
		#main_layout.setRowStretch(1, 2)
		#main_layout.setColumnStretch(1, 1)
		main_layout.setColumnStretch(0, 1)


		## Plot
		##
		self.plot, self.curve, self.curve2 = self.create_plot('Time', 'Signal', [0,5,1], [0,1500,200], ncurves=2)
		self.plot_fft, self.curve_fft, self.curve2_fft = self.create_plot('Time', 'FFt', [0,75,10], [0,0.02,0.005], ncurves=2)
		
		plot_layout = QVBoxLayout()
		plot_layout.addWidget(self.plot)
		plot_layout.addWidget(self.plot_fft)
		
		plot_groupbox = QGroupBox('Signal')
		plot_groupbox.setLayout(plot_layout)
		
		### Arena
		###
		self.plot_arena, self.curve_arena = self.create_plot('x', 'y', [-1,1,0.2], [-1,1,0.2], curve_style='o')
		
		plot_layout_arena = QHBoxLayout()
		plot_layout_arena.addWidget(self.plot_arena)
		
		plot_groupbox_arena = QGroupBox('Arena')
		plot_groupbox_arena.setLayout(plot_layout_arena)

		## Main frame and layout
		##
		main_layout.addWidget(plot_groupbox,0,0)
		main_layout.addWidget(plot_groupbox_arena,0,1,1,1)
		
		self.main_frame.setLayout(main_layout)
		self.setGeometry(30, 30, 950, 300)
		
		self.setCentralWidget(self.main_frame)

	def create_menu(self):
		self.file_menu = self.menuBar().addMenu("&File")
		
		self.start_action = self.create_action("&Start monitor",
			shortcut="Ctrl+M", slot=self.on_start, tip="Start the data monitor")
		self.stop_action = self.create_action("&Stop monitor",
			shortcut="Ctrl+T", slot=self.on_stop, tip="Stop the data monitor")
		exit_action = self.create_action("E&xit", slot=self.close, 
			shortcut="Ctrl+X", tip="Exit the application")
		
		self.start_action.setEnabled(True)
		self.stop_action.setEnabled(False)
		
		self.add_actions(self.file_menu, 
			(   self.start_action, self.stop_action,
				None, exit_action))
			
		self.help_menu = self.menuBar().addMenu("&Help")
		about_action = self.create_action("&About", 
			shortcut='F1', slot=self.on_about, 
			tip='About the monitor')
		
		self.add_actions(self.help_menu, (about_action,))

	def set_actions_enable_state(self):
		start_enable = not self.monitor_active
		stop_enable = self.monitor_active
		
		self.start_action.setEnabled(start_enable)
		self.stop_action.setEnabled(stop_enable)

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
	
	def on_start(self):
		""" Start the monitor: com_monitor thread and the update
			timer
		"""
		if self.com_monitor is not None:
			return
		
		self.data_q = Queue.Queue()
		self.error_q = Queue.Queue()
		self.com_monitor = ComMonitorThread(
			self.data_q,
			self.error_q,
			'/dev/ttyACM0',
			230400)
		self.com_monitor.start()
		
		self.data2_q = Queue.Queue()
		self.error2_q = Queue.Queue()
		self.com_monitor2 = ComMonitorThread(
			self.data2_q,
			self.error2_q,
			'/dev/ttyACM1',
			230400)
		self.com_monitor2.start()
		
		com_error = get_item_from_queue(self.error_q)
		com_error2 = get_item_from_queue(self.error2_q)
		if com_error is not None:
			QMessageBox.critical(self, 'ComMonitorThread error',
				com_error)
			self.com_monitor = None
		if com_error2 is not None:
			QMessageBox.critical(self, 'ComMonitorThread error',
				com_error2)
			self.com_monitor2 = None
			
		self.monitor_active = True
		self.set_actions_enable_state()
		
		self.timer = QTimer()
		self.connect(self.timer, SIGNAL('timeout()'), self.on_timer)
		update_freq = 1000. #Hz
		self.timer.start(1000.0 / update_freq) #ms
		
		self.timer_plot = QTimer()
		self.connect(self.timer_plot, SIGNAL('timeout()'), self.on_timer_plot)
		update_freq = 100. #Hz
		self.timer_plot.start(1000.0 / update_freq) #ms
		
		self.status_text.setText('Monitor running')
	
	def on_timer(self):
		""" Executed periodically when the monitor update timer
			is fired.
		"""
		self.read_serial_data()
		if self.livefeed.has_new_data:
			self.livefeed.append_data(self.livefeed.read_data())
		
		if self.livefeed2.has_new_data:
			self.livefeed2.append_data(self.livefeed2.read_data())
		#self.update_monitor()
		
	def on_timer_plot(self):
		self.update_monitor()

	def update_monitor(self):
		""" Updates the state of the monitor window with new 
			data. The livefeed is used to find out whether new
			data was received since the last update. If not, 
			nothing is updated.
		"""
		update1, update2 = False,False
		#if self.livefeed.has_new_data:
		if self.livefeed.updated_list:
			#data = self.livefeed.read_data()
			self.temperature_samples = self.livefeed.read_list()
			
			#self.temperature_samples.append(
				#(data['timestamp'], data['temperature']))
			#if len(self.temperature_samples) > 1000:
				#self.temperature_samples.pop(0)
			
			xdata = [s[0] for s in self.temperature_samples]
			ydata = [s[1] for s in self.temperature_samples]
			
			self.plot.setXRange(max(0,xdata[-1]-5), max(5, xdata[-1]))
			self.curve.setData(xdata, ydata, _CallSync='off')
			
			# plot fft of port 1
			#
			delta = np.array(xdata[1:])-np.array(xdata[:-1])
			#print(np.nanmean(delta),xdata[-1])#,np.nanstd(delta)
			n = len(ydata)
			fft1 = np.abs(np.fft.rfft(ydata))
			fft1 = (fft1/np.sum(fft1))[1:]
			x = np.fft.rfftfreq(n,d=np.nanmean(delta))[1:]
			
			self.curve_fft.setData(x,fft1, _CallSync='off')
			
			power_alpha = np.sum(fft1[(x>self.x_low)*(x<self.x_high)])
			update1 = True
			
		if self.livefeed2.updated_list:
			self.temperature_samples2 = self.livefeed2.read_list()

			xdata = [s[0] for s in self.temperature_samples2]
			ydata = [s[1]+400 for s in self.temperature_samples2]

			self.curve2.setData(xdata, ydata, _CallSync='off')
			
			# plot fft of port 2
			#
			n = len(ydata)
			delta = np.array(xdata[1:])-np.array(xdata[:-1])
			fft1 = np.abs(np.fft.rfft(ydata))
			fft1 = (fft1/np.sum(fft1))[1:]
			x = np.fft.rfftfreq(n,d=np.nanmean(delta))[1:]
			
			self.curve2_fft.setData(x,fft1, _CallSync='off')
			
			power_alpha2 = np.sum(fft1[(x>self.x_low)*(x<self.x_high)])
			update2 = True
		
		if (update1 and update2):
			if n>999:
				#print((power_alpha2 - power_alpha)*self.tuning_factor)
				self.ball_coordx[0] += (power_alpha2 - power_alpha)*self.tuning_factor
				self.ball_coordy[0] += 0
			else:
				self.ball_coordx[0] = 0
				self.ball_coordy[0] = 0
			self.curve_arena.setData(max(1,self.ball_coordx),self.ball_coordy, _CallSync='off')
			if abs(self.ball_coordx[0])>0.1 and self.show_one_item is False:
				winner_color = 'limegreen' if self.ball_coordx[0]<0 else 'Magenta'
				text = pg.TextItem(html=self.text_html.format(winner_color), anchor=(0.3,1.3),\
				border=QColor(winner_color), fill=(201, 165, 255, 100))
				
				self.plot_arena.addItem(text)
				self.show_one_item = True
				self.on_stop()
	
	def read_serial_data(self):
		""" Called periodically by the update timer to read data
			from the serial port.
		"""
		#qdata = list(get_all_from_queue(self.data_q))
		#if len(qdata) > 0:
			#data = dict(timestamp=qdata[-1][1], 
						#temperature=decode_output(qdata[-1][0]))
			#self.livefeed.add_data(data)
		
		qdata = list(get_item_from_queue(self.data_q))
		tstamp = qdata[1]
		output = decode_output(qdata[0])
		if len(output) > 0:
			data = dict(timestamp=tstamp, 
						temperature=float(np.nanmean(output)))
			self.livefeed.add_data(data)
			
		qdata2 = list(get_item_from_queue(self.data2_q))
		tstamp = qdata2[1]
		output = decode_output(qdata2[0])
		if len(output) > 0:
			data = dict(timestamp=tstamp, 
						temperature=float(np.nanmean(output)))
			self.livefeed2.add_data(data)
			

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