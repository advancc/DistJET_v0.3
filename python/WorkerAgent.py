import Queue
import datetime
import json
import os,sys
import select
import subprocess
import threading
import multiprocessing
import time
import traceback

import IR_Buffer_Module as IM

import HealthDetect as HD
from BaseThread import BaseThread
from MPI_Wrapper import Tags ,Client
from Util import logger
from WorkerRegistry import WorkerStatus
from python.Util import Config
from python.Util import Package

wlog = None

class status:
    (SUCCESS, FAIL, TIMEOUT, OVERFLOW, ANR) = range(0,5)
    DES = {
        FAIL: 'Task fail, return code is not zero',
        TIMEOUT: 'Run time exceeded',
        OVERFLOW: 'Memory overflow',
        ANR: 'No responding'
    }
    @staticmethod
    def describe(stat):
        if status.DES.has_key(stat):
            return status.DES[stat]


class HeartbeatThread(BaseThread):
    """
    ping to master, provide information and requirement
    """
    def __init__(self, client, worker_agent, cond):
        BaseThread.__init__(self, name='HeartbeatThread')
        self._client = client
        self.worker_agent = worker_agent
        self.queue_lock = threading.RLock()
        self.acquire_queue = Queue.Queue()         # entry = key:val
        self.interval = Conf.Config.getCFGattr('HeartBeatInterval') if Conf.Config.getCFGattr('HeartBeatInterval') else 1
        self.cond = cond
        global wlog
    def run(self):
        #add first time to ping master, register to master
        send_dict = {}
        send_dict['flag'] = 'FP'
        send_dict[Tags.MPI_REGISTY] = {'capacity':self.worker_agent.capacity}
        send_dict['ctime'] = time.time()
        send_dict['uuid'] = self.worker_agent.uuid
        send_str = Package.pack_obj(send_dict)
        wlog.debug('[HeartBeat] Send msg = %s'%send_dict)
        ret = self._client.send_string(send_str, len(send_str),0,Tags.MPI_REGISTY)
        if ret != 0:
            #TODO send error,add handler
            pass

        # wait for the wid and init msg from master
        self.cond.acquire()
        self.cond.wait()
        self.cond.release()

        while not self.get_stop_flag():
            try:
                self.queue_lock.acquire()
                send_dict.clear()
                while not self.acquire_queue.empty():
                    tmp_d = self.acquire_queue.get()
                    if send_dict.has_key(tmp_d.keys()[0]):
                        wlog.warning('[HeartBeatThread]: Reduplicated key=%s when build up heart beat message, skip it'%tmp_d.keys()[0])
                        continue
                    send_dict = dict(send_dict, **tmp_d)
                self.queue_lock.release()
                send_dict['Task'] = {}
                while not self.worker_agent.task_completed_queue.empty():
                    task = self.worker_agent.task_completed_queue.get()
                    send_dict['Task'] = dict(send_dict['Task'],**task)
                send_dict['uuid'] = self.worker_agent.uuid
                send_dict['wid'] = self.worker_agent.wid
                send_dict['health'] = self.worker_agent.health_info()
                send_dict['rTask'] = self.worker_agent.getRuntasklist()
                send_dict['ctime'] = time.time()
                # before send heartbeat, sync agent status
                self.worker_agent.status_lock.acquire()
                send_dict['wstatus'] = self.worker_agent.status
                self.worker_agent.status_lock.release()
                send_str = json.dumps(send_dict)
#                wlog.debug('[HeartBeat] Send msg = %s'%send_str)
                ret = self._client.send_string(send_str, len(send_str), 0, Tags.MPI_PING)
                if ret != 0:
                    #TODO add send error handler
                    pass
            except Exception:
                wlog.error('[HeartBeatThread]: unkown error, thread stop. msg=%s', traceback.format_exc())
                break
            else:
                time.sleep(self.interval)

        # the last time to ping Master
        if not self.acquire_queue.empty():
            remain_command = ''
            while not self.acquire_queue.empty():
                remain_command+=self.acquire_queue.get().keys()
            wlog.waring('[HeartBeat] Acquire Queue has more command, %s, ignore them'%remain_command)
        send_dict.clear()
        send_dict['wid'] = self.worker_agent.wid
        send_dict['uuid'] = self.worker_agent.uuid
        send_dict['flag'] = 'LP'
        send_dict['Task'] = {}
        while not self.worker_agent.task_completed_queue.empty():
            task = self.worker_agent.task_completed_queue.get()
            #FIXME: change to task obj
            send_dict['Task'] = dict(send_dict['Task'],**task)
        # add node health information
        send_dict['health'] = self.worker_agent.health_info()
        send_dict['ctime'] = time.time()
        #send_dict['wstatus'] = self.worker_agent.worker.status
        send_str = Package.pack_obj(send_dict)
        wlog.debug('[HeartBeat] Send msg = %s'%send_dict)
        ret = self._client.send_string(send_str, len(send_str), 0, Tags.MPI_PING)
        if ret != 0:
            #TODO add send error handler
            pass



    def set_ping_duration(self, interval):
        self.interval = interval


class WorkerAgent:

    def __init__(self,name=None,capacity=1):
        import uuid as uuid_mod
        self.uuid = str(uuid_mod.uuid4())
        if name is None:
            name = self.uuid
        global wlog
        wlog = logger.getLogger('Worker_%s'%name)
        self.worker_class = None

        self.recv_buff = IM.IRecv_buffer()
        self.__should_stop = False
        Config.Config()
        self.cfg = Config.Config
        if self.cfg.isload():
            wlog.debug('[Agent] Loaded config file')
        wlog.debug('[Agent] Start to connect to service <%s>' % self.cfg.getCFGattr('svc_name'))
        self.client = Client(self.recv_buff, self.cfg.getCFGattr('svc_name'), self.uuid)
        ret = self.client.initial()
        if ret != 0:
            #TODO client initial error, add handler
            wlog.error('[Agent] Client initialize error, errcode = %d'%ret)
            #exit()

        self.wid = None
        self.appid = None
        self.capacity = capacity
        self.task_queue = Queue.Queue(maxsize=self.capacity) #store task obj
        self.task_completed_queue = Queue.Queue()
        self.ignoreTask=[]

        self.initExecutor=None #init task obj
        self.tmpLock = threading.RLock()
        self.finExecutor=None

        self.fin_flag = False
        self.initial_flag = False
        self.app_fin_flag = False
        self.halt_flag = False

        self.heartcond = threading.Condition()
        self.heartbeat = HeartbeatThread(self.client, self, self.heartcond)

        self.worker_list = {}
        self.worker_status={}
        self.cond_list = {}

    def run(self):
        wlog.debug('[Agent] WorkerAgent run...')
        self.heartbeat.start()
        wlog.debug('[WorkerAgent] HeartBeat thread start...')
        while not self.__should_stop:
            time.sleep(0.1) #TODO temporary config for loop interval
            if not self.recv_buff.empty():
                msg = self.recv_buff.get()
                if msg.tag == -1:
                    continue
                recv_dict = Package.unpack_obj(msg.sbuf)
                for k,v in recv_dict.items():
                    # registery info v={wid:val,init:[TaskObj], appid:v, wmp:worker_module_path}
                    if int(k) == Tags.MPI_REGISTY_ACK:
                        if v.has_key('flag') and v['flag'] == 'NEWAPP':
                            wlog.debug('[WorkerAgent] Receive New App msg = %s' % v)
                            v['wid'] = self.wid
                            self.appid = v['appid']
                            self.task_queue.queue.clear()
                            self.task_completed_queue.queue.clear()
                            self.ignoreTask = []
                            self.tmpLock.acquire()
                            try:
                                self.initExecutor = None
                                self.finExecutor = None
                            finally:
                                self.tmpLock.release()
                            self.fin_flag = False
                            self.app_fin_flag = False
                            self.halt_flag = False
                        else:
                            wlog.debug('[WorkerAgent] Receive Registry_ACK msg = %s' % v)
                        worker_path = v['wmp']
                        if worker_path is not None and worker_path!='None':
                            module_path = os.path.abspath(worker_path)
                            sys.path.append(os.path.dirname(module_path))
                            worker_name = os.path.basename(module_path)
                            if worker_name.endswith('.py'):
                                worker_name = worker_name[:-3]
                            try:
                                worker_module = __import__(worker_name)
                                if worker_module.__dict__.has_key(worker_name) and callable(
                                        worker_module.__dict__[worker_name]):
                                    self.worker_class = worker_module.__dict__[worker_name]
                                    wlog.info('[Agent] Load specific worker class = %s' % self.worker_class)
                            except Exception:
                                wlog.error('[Agent] Error when import worker module %s, path = %s,errmsg=%s' % (
                                worker_name, worker_path, traceback.format_exc()))
                        else:
                            wlog.warning('[Agent] No specific worker input, use default')
                        try:
                            self.wid = v['wid']
                            self.appid = v['appid']
                            self.tmpLock.acquire()
                            self.iniExecutor = v['init']
                            self.tmpLock.release()

                            # notify worker initialize
                            wlog.info('[Agent] Start up worker and initialize')
                            for i in range(self.capacity):
                                self.cond_list.append(threading.Condition())
                                self.worker_list[i]=Worker(i, self, self.cond_list[i], worker_class=self.worker_class)
                                self.worker_status[i] = WorkerStatus.NEW
                                wlog.debug('[Agent] Worker %s start' % i)
                                self.worker_list[i].start()

                            # notify the heartbeat thread
                            wlog.debug('[WorkerAgent] Wake up the heartbeat thread')
                            self.heartcond.acquire()
                            self.heartcond.notify()
                            self.heartcond.release()
                        except Exception:
                            pass
                    # add tasks  v=[Task obj]
                    elif int(k) == Tags.TASK_ADD:
                        tasklist = v
                        self.halt_flag = False
                        wlog.debug('[WorkerAgent] Add new task : %s' % ([task.id for task in tasklist]))
                        for task in tasklist:
                            self.task_queue.put(task)
                        count = len(tasklist)
                        for worker_id, st in self.worker_status.keys():
                            if st == WorkerStatus.IDLE:
                                wlog.debug('[Agent] Worker %s IDLE, wake up worker' % worker_id)
                                self.cond_list[worker_id].acquire()
                                self.cond_list[worker_id].notify()
                                self.cond_list[worker_id].release()
                                count-=1
                                if count == 0:
                                    break
                    # remove task, v=tid






class Worker(BaseThread):
    #TODO
    pass