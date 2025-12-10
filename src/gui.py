import sys
import threading
from typing import Optional
from PySide6 import QtWidgets, QtCore

from .chat.session import ChatSession
from .transport.tcp_transport import TcpTransport, TcpListener
from .transport.bluetooth_transport import BluetoothTransport


class ChatWorker(QtCore.QThread):
    message_received = QtCore.Signal(str)
    disconnected = QtCore.Signal(str)

    def __init__(self, session: ChatSession):
        super().__init__()
        self.session = session
        self._stop = threading.Event()

    def run(self):
        try:
            while not self._stop.is_set():
                msg = self.session.recv_message()
                self.message_received.emit(msg)
        except Exception as exc:
            self.disconnected.emit(str(exc))
        finally:
            self.session.close()

    def stop(self):
        self._stop.set()
        try:
            self.session.close()
        except Exception:
            pass


class ConnectWorker(QtCore.QThread):
    connected = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, mode: str, transport: str, host: str, port: int, channel: int, name: str):
        super().__init__()
        self.mode = mode
        self.transport = transport
        self.host = host
        self.port = port
        self.channel = channel
        self.name = name

    def run(self):
        try:
            if self.transport == "tcp":
                t = TcpTransport.connect(self.host, self.port) if self.mode == "connect" else TcpTransport.listen(self.port)
            else:
                t = BluetoothTransport.connect(self.host, self.channel) if self.mode == "connect" else BluetoothTransport.listen(self.channel)
            session = ChatSession(t, username=self.name)
            session.handshake()
            self.connected.emit(session)
        except Exception as exc:
            self.failed.emit(str(exc))


class HostTcpWorker(QtCore.QThread):
    client_connected = QtCore.Signal(str)
    client_disconnected = QtCore.Signal(str, str)
    message_received = QtCore.Signal(str, str)
    failed = QtCore.Signal(str)
    status = QtCore.Signal(str)

    def __init__(self, port: int, name: str):
        super().__init__()
        self.port = port
        self.name = name
        self._stop = threading.Event()
        self._sessions: list[ChatSession] = []
        self._labels: dict[ChatSession, str] = {}
        self._names: set[str] = set()
        self._lock = threading.Lock()
        self._listener: TcpListener | None = None

    def run(self):
        try:
            self._listener = TcpListener(self.port)
            self.status.emit(f"listening on {self.port}")
            while not self._stop.is_set():
                try:
                    t = self._listener.accept()
                except OSError:
                    break
                try:
                    sess = ChatSession(t, username=self.name)
                    sess.handshake()
                    label = sess.peer_label
                    if self._name_taken(label):
                        sess.close()
                        self.client_disconnected.emit(label, "username already connected")
                        continue
                except Exception as exc:
                    try:
                        t.close()
                    except Exception:
                        pass
                    self.client_disconnected.emit("unknown", str(exc))
                    continue

                self._add_session(sess)
                self.client_connected.emit(label)
                threading.Thread(target=self._reader, args=(sess,), daemon=True).start()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.stop()

    def _reader(self, sess: ChatSession):
        label = sess.peer_label
        try:
            while not self._stop.is_set():
                msg = sess.recv_message()
                self.message_received.emit(label, msg)
        except Exception as exc:
            self.client_disconnected.emit(label, str(exc))
        finally:
            self._remove_session(sess)
            sess.close()

    def _add_session(self, sess: ChatSession):
        with self._lock:
            self._sessions.append(sess)
            self._labels[sess] = sess.peer_label
            self._names.add(sess.peer_label)

    def _remove_session(self, sess: ChatSession):
        with self._lock:
            if sess in self._sessions:
                self._sessions.remove(sess)
            if sess in self._labels:
                self._labels.pop(sess, None)
            if hasattr(sess, "peer_label") and sess.peer_label in self._names:
                self._names.discard(sess.peer_label)

    def _name_taken(self, label: str) -> bool:
        with self._lock:
            return label in self._names

    def broadcast(self, text: str, prefix: str | None = None):
        payload = f"{prefix}: {text}" if prefix else text
        with self._lock:
            targets = list(self._sessions)
        for sess in targets:
            try:
                sess.send_message(payload)
            except Exception:
                self._remove_session(sess)
                sess.close()

    def send_to(self, target_label: str, text: str, sender: str | None = None):
        payload = f"{sender}: {text}" if sender else text
        target_sess = None
        with self._lock:
            for sess in self._sessions:
                if self._labels.get(sess) == target_label:
                    target_sess = sess
                    break
        if target_sess is None:
            raise ConnectionError(f"target {target_label} not connected")
        try:
            target_sess.send_message(payload)
        except Exception as exc:
            self._remove_session(target_sess)
            target_sess.close()
            raise exc

    def forward_from(self, sender_label: str, text: str):
        payload = f"{sender_label}: {text}"
        with self._lock:
            targets = [(s, self._labels.get(s)) for s in self._sessions]
        for sess, lbl in targets:
            if lbl == sender_label:
                continue
            try:
                sess.send_message(payload)
            except Exception:
                self._remove_session(sess)
                sess.close()

    def stop(self):
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            if self._listener:
                self._listener.close()
        except Exception:
            pass
        with self._lock:
            for sess in list(self._sessions):
                try:
                    sess.close()
                except Exception:
                    pass
            self._sessions.clear()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Beef2Beef")

        self.session: Optional[ChatSession] = None
        self.worker: Optional[ChatWorker] = None
        self.connect_worker: Optional[ConnectWorker] = None
        self.host_worker: Optional[HostTcpWorker] = None

        # Controls
        self.host_edit = QtWidgets.QLineEdit("127.0.0.1")
        self.port_edit = QtWidgets.QLineEdit("8000")
        self.name_edit = QtWidgets.QLineEdit("anon")
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["connect", "listen"])
        self.transport_combo = QtWidgets.QComboBox()
        self.transport_combo.addItems(["tcp", "bt"])
        self.bt_channel_edit = QtWidgets.QLineEdit("3")
        self.bt_channel_label = QtWidgets.QLabel("BT Channel:")
        self.target_label = QtWidgets.QLabel("Target:")
        self.target_combo = QtWidgets.QComboBox()
        self.target_combo.addItem("All")

        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.setEnabled(False)

        self.messages = QtWidgets.QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.input_edit = QtWidgets.QLineEdit()

        self.status_label = QtWidgets.QLabel("Disconnected")

        # Top row: IP/Port
        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(QtWidgets.QLabel("IP / MAC:"))
        row1.addWidget(self.host_edit, 1)
        row1.addWidget(QtWidgets.QLabel("Port:"))
        row1.addWidget(self.port_edit)

        # Second row
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("Name:"))
        row2.addWidget(self.name_edit, 1)
        row2.addWidget(QtWidgets.QLabel("Transport:"))
        row2.addWidget(self.transport_combo)
        row2.addWidget(QtWidgets.QLabel("Mode:"))
        row2.addWidget(self.mode_combo)
        row2.addWidget(self.target_label)
        row2.addWidget(self.target_combo)
        row2.addWidget(self.bt_channel_label)
        row2.addWidget(self.bt_channel_edit)

        top_box = QtWidgets.QHBoxLayout()
        top_box.addWidget(self.connect_btn)
        top_box.addWidget(self.status_label)

        send_box = QtWidgets.QHBoxLayout()
        send_box.addWidget(self.input_edit, 1)
        send_box.addWidget(self.send_btn)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addLayout(top_box)
        layout.addWidget(self.messages, 1)
        layout.addLayout(send_box)

        container = QtWidgets.QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Wiring
        self.connect_btn.clicked.connect(self.on_connect)
        self.send_btn.clicked.connect(self.on_send)
        self.transport_combo.currentTextChanged.connect(self.on_transport_change)
        self.mode_combo.currentTextChanged.connect(self.on_mode_change)
        self.input_edit.returnPressed.connect(self.on_send)
        self.on_transport_change(self.transport_combo.currentText())
        self.on_mode_change(self.mode_combo.currentText())

    def log(self, text: str):
        self.messages.appendPlainText(text)

    def on_transport_change(self, value: str):
        is_bt = value == "bt"
        self.port_edit.setEnabled(not is_bt)
        self.bt_channel_edit.setVisible(is_bt)
        self.bt_channel_label.setVisible(is_bt)

    def on_mode_change(self, value: str):
        is_listen = value == "listen"
        if is_listen and self.transport_combo.currentText() == "tcp":
            self.host_edit.setPlaceholderText("(ignored for listen)")
        else:
            self.host_edit.setPlaceholderText("")
        self.target_label.setVisible(is_listen)
        self.target_combo.setVisible(is_listen)

    def on_connect(self):
        if self.host_worker or self.session:
            self.disconnect_session()
            return
        if self.connect_worker:
            return

        transport = self.transport_combo.currentText()
        mode = self.mode_combo.currentText()
        host = self.host_edit.text().strip()
        name = self.name_edit.text().strip() or "anon"
        try:
            port = int(self.port_edit.text()) if self.port_edit.text() else 0
            channel = int(self.bt_channel_edit.text()) if self.bt_channel_edit.text() else 0
        except ValueError:
            QtWidgets.QMessageBox.critical(self, "Invalid input", "Port/channel must be numbers")
            return

        self.connect_btn.setEnabled(False)

        if mode == "listen" and transport == "tcp":
            self.status_label.setText("Listening...")
            self.log("[system] listening...")
            self.host_worker = HostTcpWorker(port, name)
            self.host_worker.client_connected.connect(self.on_host_client_connected)
            self.host_worker.client_disconnected.connect(self.on_host_client_disconnected)
            self.host_worker.message_received.connect(self.on_host_message)
            self.host_worker.failed.connect(self.on_connect_failed)
            self.host_worker.status.connect(lambda s: self.log(f"[system] {s}"))
            self.host_worker.start()
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Stop")
            self.send_btn.setEnabled(True)
            self.status_label.setText(f"Listening on {port}")
        else:
            self.status_label.setText("Listening..." if mode == "listen" else "Connecting...")
            self.log(f"[system] {self.status_label.text().lower()}")

            self.connect_worker = ConnectWorker(mode, transport, host, port, channel, name)
            self.connect_worker.connected.connect(self.on_connected)
            self.connect_worker.failed.connect(self.on_connect_failed)
            self.connect_worker.start()

    def disconnect_session(self):
        if self.connect_worker:
            try:
                self.connect_worker.requestInterruption()
                self.connect_worker.quit()
                self.connect_worker.wait(1000)
            except Exception:
                pass
            self.connect_worker = None
        if self.host_worker:
            self.host_worker.stop()
            self.host_worker.wait(1000)
            self.host_worker = None
        self.target_combo.clear()
        self.target_combo.addItem("All")
        if self.worker:
            self.worker.stop()
            self.worker.wait(1000)
            self.worker = None
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None
        self.connect_btn.setText("Connect")
        self.send_btn.setEnabled(False)
        self.status_label.setText("Disconnected")
        self.log("[system] disconnected")

    def on_disconnect(self, reason: str):
        self.log(f"[disconnect] {reason}")
        self.disconnect_session()

    def on_message(self, msg: str):
        label = self.session.peer_label if self.session else "peer"
        if ": " in msg:
            prefix, rest = msg.split(": ", 1)
            label, msg = prefix, rest
        self.log(f"[{label}] {msg}")

    def on_host_message(self, label: str, msg: str):
        is_private = msg.startswith("[PRIVATE] ")
        clean_msg = msg[len("[PRIVATE] "):] if is_private else msg
        self.log(f"[{label}{' PRIVATE' if is_private else ''}] {clean_msg}")
        if not is_private and self.host_worker:
            try:
                self.host_worker.forward_from(label, clean_msg)
            except Exception as exc:
                self.log(f"[forward failed] {exc}")
        if label not in [self.target_combo.itemText(i) for i in range(self.target_combo.count())]:
            self.target_combo.addItem(label)

    def on_host_client_connected(self, label: str):
        self.log(f"[join] {label}")

    def on_host_client_disconnected(self, label: str, reason: str):
        self.log(f"[leave] {label} ({reason})")

    def on_connected(self, session: ChatSession):
        if self.connect_worker is None:
            session.close()
            return
        self.connect_worker = None
        self.session = session
        self.worker = ChatWorker(session)
        self.worker.message_received.connect(self.on_message)
        self.worker.disconnected.connect(self.on_disconnect)
        self.worker.start()

        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Disconnect")
        self.send_btn.setEnabled(True)
        self.status_label.setText(f"Connected to {session.peer_label}")
        self.log(f"[system] connected to {session.peer_label}")

    def on_connect_failed(self, reason: str):
        self.connect_worker = None
        self.connect_btn.setEnabled(True)
        self.status_label.setText("Disconnected")
        QtWidgets.QMessageBox.critical(self, "Connection failed", reason)
        self.log(f"[connect failed] {reason}")

    def on_send(self):
        text = self.input_edit.text()
        if not text:
            return
        if self.host_worker:
            try:
                target = self.target_combo.currentText()
                sender = self.name_edit.text() or "me"
                if target and target != "All":
                    payload = f"[PRIVATE] {text}"
                    self.host_worker.send_to(target, payload, sender)
                    self.log(f"[me -> {target} PRIVATE] {text}")
                else:
                    self.host_worker.broadcast(text, prefix=sender)
                    self.log(f"[me] {text}")
            except Exception as exc:
                self.log(f"[send failed] {exc}")
                self.disconnect_session()
            self.input_edit.clear()
            return

        if not self.session:
            return
        try:
            self.session.send_message(text)
            my_label = self.session.username if self.session else "me"
            self.log(f"[{my_label}] {text}")
            self.input_edit.clear()
        except Exception as exc:
            self.log(f"[send failed] {exc}")
            self.disconnect_session()

    def closeEvent(self, event):
        self.disconnect_session()
        return super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.resize(600, 500)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
