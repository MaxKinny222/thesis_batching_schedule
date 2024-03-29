from collections import defaultdict
from glob import glob
from random import choice, sample
from myUtils import gen, gen_over_sampling, gen_completely_separated, read_img
import time
import cv2
import numpy as np
import pandas as pd
from keras.callbacks import ModelCheckpoint, ReduceLROnPlateau
from keras.layers import Input, Dense, GlobalMaxPool2D, GlobalAvgPool2D, Concatenate, Multiply, Dropout, Subtract
from keras.models import Model
from keras.optimizers import Adam
from keras_vggface.utils import preprocess_input
from keras_vggface.vggface import VGGFace
from keras import backend as K
import math
import random
import threading
import matplotlib.pyplot as pt
from tqdm import tqdm
import seaborn as sns
from sklearn import linear_model
import copy
import tensorflow as tf
from keras.callbacks import TensorBoard
import main_multiThread
from keras.applications.resnet50 import ResNet50

def prepare():
    global picture_files, G, model, lock, submission,\
        signal, picture_files_tmp, test_path, file_path
    basestr = 'splitmodel'
    file_path = './data' + "/vgg_face_" + basestr + ".h5"
    test_path = "./data/test/"
    submission = pd.read_csv('./data/sample_submission.csv')
    picture_files_tmp = submission.img_pair.values
    X1 = [test_path + x.split("-")[0] for x in picture_files_tmp]
    X2 = [test_path + x.split("-")[1] for x in picture_files_tmp]
    picture_files = list(zip(X1, X2))
    G = tf.get_default_graph()
    model = ResNet50(include_top=False)
    # model.load_weights(file_path)

    lock = threading.Lock()
    signal = threading.Event()


def nextTime(rateParameter):
    return -math.log(1.0 - random.random()) / rateParameter


def myLoss(margin):
    def Loss(y_true, y_pred):
        return (1-y_true)*0.5*(y_pred)^2 + y_true*0.5*K.max(0, margin-y_pred)^2
    return Loss


def chunker(seq, size=32):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))


def detect_outliers2(df):
    outlier_indices = []

    # 1st quartile (25%)
    Q1 = np.percentile(df, 25)
    # 3rd quartile (75%)
    Q3 = np.percentile(df, 75)
    # Interquartile range (IQR)
    IQR = Q3 - Q1

    # outlier step
    outlier_step = 1.5 * IQR
    for nu in df:
        if (nu < Q1 - outlier_step) | (nu > Q3 + outlier_step):
            df.remove(nu)
    return df


def add_task():
    global task_num, request_end_flag, picture_files, working_flag
    for wt in arriving_proccess:
        if not working_flag:
            lock.acquire()
            task_queue.append(choice(picture_files))
            cur_time = time.time()
            task_num += 1
            if workload_num:
                workload_num.append(workload_num[-1])
                workload_time.append(cur_time)
            workload_time.append(cur_time)
            workload_num.append(task_num)
            lock.release()
        if len(task_queue) >= 100:
            signal.set()
        time.sleep(wt)  # wait until next arrival
        # print("plus:", task_num)
    request_end_flag = True


def do_task(schedule):
    global task_num, request_end_flag, G, model, working_flag  # , workload_time, workload_num, lock
    while task_queue or not request_end_flag:
        if not task_queue:  # in case that MBTT is too large
            continue
        # start using schedule
        delay(schedule)
        # start sending the batch and do the tasks
        working_flag = True
        lock.acquire()
        pictures_tmp = copy.copy(task_queue)  # cpu bound
        task_queue[:] = []  # cpu bound
        lock.release()
        ### do tasks
        time.sleep(random.normalvariate(0.2, 0.01))  # simulate the overhead consume(IO bound)
        ## predict
        t1 = time.time()
        picture1 = [read_img(x[0]) for x in pictures_tmp]  # (IO bound)
        picture2 = [read_img(x[1]) for x in pictures_tmp]  # (IO bound)
        with G.as_default():
            model.predict([picture1, picture2])  # (IO bound)
        ## dequeue
        cur_time = time.time()
        predit_times.append((cur_time, time.time() - t1))
        lock.acquire()
        task_num -= len(pictures_tmp)
        if workload_num:
            workload_num.append(workload_num[-1])
            workload_time.append(cur_time)
        workload_time.append(cur_time)
        workload_num.append(task_num)
        lock.release()
        working_flag = False
        signal.clear()
        # print("do task", tmp)
        # print("minus:", task_num)


def simulate(schedule):
    add_task_t = threading.Thread(target=add_task)
    do_task_t = threading.Thread(target=do_task, args=(schedule,))
    add_task_t.start()
    do_task_t.start()
    add_task_t.join()
    do_task_t.join()


def delay(schedule):
    schedule.run()


class Schedule:
    def __init__(self, latency_threshold, run_fun, batch_size_threshold=0):
        self.latency_threshold = latency_threshold
        self.run_fun = run_fun
        self.batch_size_threshold = batch_size_threshold

    def run(self):
        self.run_fun(self.latency_threshold, self.batch_size_threshold)

'''
    schedules' set
'''


def vanilla_schedule_fun(latency_threshold, batch_size_threshold):
    time.sleep(latency_threshold)


def NinetyPercent_schedule_fun(latency_threshold, batch_size_threshold):
    signal.wait(3)


if __name__ == '__main__':
    '''
        prepare data
    '''
    prepare()

    # '''
    #     experiment setup
    # '''
    # batch_size_threshold = 100
    #
    # latency_threshold = 2
    #
    # experiment_times = 5
    #
    # schedule_nums = 2
    #
    # simulating_time = 3600*0 + 60*0 + 1*5
    #
    # MTBT = 1 / 83.333  # Mean Time Between Task
    #
    # '''
    #     warm up GPU
    # '''
    # for batch in tqdm(chunker(picture_files_tmp, 64)):
    #     time_start = time.time()
    #     X1 = [x.split("-")[0] for x in batch]
    #     X1 = [read_img(test_path + x) for x in X1]
    #     X2 = [x.split("-")[1] for x in batch]
    #     X2 = [read_img(test_path + x) for x in X2]
    #     model.predict([X1, X2])
    #
    # '''
    #     simulation experiment begin
    # '''
    # # load all schedule_fun
    # schedule_fn_list = [eval(x) for x in dir(main_multiThread) if 'schedule_fun' in x]
    # area_list = []
    # predit_times = []
    # for _ in tqdm(range(experiment_times)):  # range(experiment times)
    #     arriving_proccess = []
    #     total_arriving_time = 0
    #     while total_arriving_time < simulating_time:
    #         next_time = nextTime(1/MTBT)  # nextTime(lambda)
    #         arriving_proccess.append(next_time)
    #         total_arriving_time += next_time
    #     pt.figure()
    #     for schedule_fun in schedule_fn_list:
    #         working_flag = False  # producer thread will monitor it pretending to feed to another worker
    #         request_end_flag = False  # mark whether producer thread is end
    #         task_queue = []
    #         task_num = 0  # waiting tasks' num
    #         workload_time = []
    #         workload_num = []
    #         current_schedule = Schedule(latency_threshold, schedule_fun, batch_size_threshold)
    #         # start simulation
    #         simulate(current_schedule)
    #         # shift time to zero
    #         workload_time = [x-workload_time[0] for x in workload_time]
    #         # sort by workload_time
    #         workload_data = np.array([workload_time, workload_num])
    #         # workload_data = workload_data.T[np.lexsort(workload_data[::-1, :])].T
    #         # compute area
    #         area = 0
    #         for i in range(len(workload_time)):
    #             if i == len(workload_time)-1:
    #                 break
    #             area += workload_data[1, i]*(workload_data[0, i+1] - workload_data[0, i])
    #         area_list.append(area/workload_time[-1])
    #         pt.plot(workload_data[0, :], workload_data[1, :], label=schedule_fun.__name__[:-4])
    #         pt.legend()
    #     pt.show()
    #
    # '''
    #     process experiment results
    # '''
    # # compare area
    # area_data = np.empty((schedule_nums, experiment_times))
    # sub_id_list = [0]*schedule_nums
    # for id, el in enumerate(area_list):
    #     mod = (id+1) % schedule_nums
    #     area_data[mod-1, sub_id_list[mod-1]] = el
    #     sub_id_list[mod-1] += 1
    # if experiment_times > 1:
    #     pt.figure()
    #     for id in range(schedule_nums):
    #         sns.distplot(area_data[id, :], label=schedule_fn_list[id].__name__[:-4])
    #         pt.legend()
    # pt.show()
    # print("Finish simulation experiment")

    '''
        estimate parameter
    '''
    ########### plot A(n)
    model = ResNet50(include_top=False)
    computing_time_tmp = []
    start_bs = 1
    end_bs = 100
    delta_bs = 1
    for batchsize in tqdm(list(range(start_bs, end_bs, delta_bs))):
        predictions = []
        time_per_batch = []
        for batch in tqdm(chunker(submission.img_pair.values, batchsize)):
            time_start = time.time()

            X1 = [x.split("-")[0] for x in batch]
            X1 = [read_img(test_path + x) for x in X1]

            time_start = time.time()

            model.predict([X1])

            time_end = time.time()

            time_per_batch.append(time_end - time_start)
        computing_time_tmp.append(detect_outliers2(time_per_batch))
    batch_size_tmp = list(range(start_bs, end_bs, delta_bs))
    computing_time = []
    batch_size = []
    for id, el in enumerate(computing_time_tmp):
        for elel in el:
            computing_time.append([elel])
            batch_size.append([batch_size_tmp[id]])
    pt.plot(batch_size, computing_time, 'r*')
    regression_model = linear_model.LinearRegression()
    regression_model.fit(batch_size, computing_time)
    predictions = regression_model.predict([[x] for x in batch_size_tmp])
    pt.plot(batch_size_tmp, predictions.ravel())
    print("K: ", regression_model.coef_.ravel()[0])
    # sns.violinplot(data=pd.DataFrame(full_data_predict).T)
