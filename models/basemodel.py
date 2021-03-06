import torch
import torch.optim as optim
from torch.utils.tensorboard import SummaryWriter
from datasets.datasets import CustomDataLoader

import os
import time

class BaseModel():
    def __init__(self, opt):
        self.opt = opt
        self.ckpt_path = os.path.join(opt.save_path,opt.name)
        self.num_classes = opt.num_classes
        self.lr = opt.learning_rate
        self.momentum = opt.momentum
        self.betas = (opt.beta1, opt.beta2)
        self.image_pattern = opt.image_pattern
        self.save_model_freq = opt.save_model_freq
        self.ed_epoch = opt.niter + opt.niter_decay + 1
        self.st_epoch = opt.epoch_count

    def initialize(self):
        pass

    def train(self):
        pass

    def test(self):
        pass

    def forward(self):
        pass

    def setup(self):
        def mkdir(path):
            if not os.path.exists(path):
                os.mkdir(path)

        mkdir(self.ckpt_path)

        if not self.opt.eval:
            self.schedulers = [get_scheduler(optimizer, self.opt) for optimizer in self.optimizers]
        # torch.backends.cudnn.benchmark = True
        if self.opt.eval:
            self.opt.not_flip = True
            self.opt.not_rotate = True
            self.opt.batch_size = 1
        self.batch_size = self.opt.batch_size
        self.data_loader = CustomDataLoader()
        self.data_loader.initialize(self.opt)
        self.datasets = self.data_loader.load_data()
        self.data_size = len(self.datasets)
        self.writer = SummaryWriter(os.path.join(self.ckpt_path, 'logs'))

        self.start_time = time.time()
        self.pre_epoch_time = self.start_time
        self.pre_iter_time = self.start_time


    def eval(self):
        for net in self.models.keys():
            self.models[net].eval()

    def save(self, epoch='latest'):
        if epoch != 'latest':
            training_state = {'epoch': epoch, 'lr': self.lr}
            torch.save(training_state, os.path.join(self.ckpt_path, 'model_states.pth'))

        for net in self.models.keys():
            torch.save(self.models[net].state_dict(), os.path.join(self.ckpt_path, '{}_'.format(epoch) + net + '_params.pth'))

    def load(self, epoch='latest'):
        print('\n**************** loading model ******************')

        for net in self.models.keys():
            file_path = os.path.join(self.ckpt_path, epoch + '_' + net + '_params.pth')
            if not os.path.exists(file_path):
                raise FileNotFoundError('%s is not found.' % file_path)
            self.models[net].load_state_dict(torch.load(file_path))

        print('\n********** load model successfully **************')

    def update_learning_rate(self):
        for scheduler in self.schedulers:
            scheduler.step()

        self.lr = self.optimizers[0].param_groups[0]['lr']

    def set_requires_grad(self, nets, requires_grad):
        if not isinstance(nets, list):
            nets = [nets]
        for net in nets:
            if net is not None:
                for param in net.parameters():
                    param.requires_grad = requires_grad

    def read_input(self, input):
        self.real_A = input['A'].cuda()
        self.real_B = input['B'].cuda()

    def set_state_dict(self):
        pass

    # output training message iter ver.
    def print_training_iter(self, epoch, idx):
        current_time = time.time()
        iter_time = current_time - self.pre_iter_time
        self.pre_iter_time = current_time

        print(
            'iter_time: %4.4f s, epoch: [%d/%d], step: [%d/%d], learning_rate: %.7f'
            %
            (iter_time, epoch, self.ed_epoch-1, idx+1, self.data_size // self.batch_size, self.lr), end=''
        )

        self.train_log = open(os.path.join(self.ckpt_path, 'train_log.txt'), 'a')
        self.train_log.write(
            'iter_time: %4.4f s, epoch: [%d/%d], step: [%d/%d], learning_rate: %.7f'
            %
            (iter_time, epoch, self.ed_epoch - 1, idx + 1, self.data_size // self.batch_size, self.lr)
        )

        for label in self.state_dict.keys():
            print(', %s: %.7f' % (label, self.state_dict[label]), end='')
            self.train_log.write(', %s: %.7f' % (label, self.state_dict[label]))
            self.writer.add_scalar(label, self.state_dict[label], global_step=self.step)

        print('')
        self.train_log.write('\n')
        self.train_log.close()

    # output training message epoch ver.
    def print_training_epoch(self, epoch):
        current_time = time.time()
        epoch_time = current_time - self.pre_epoch_time
        total_time = current_time - self.start_time
        self.pre_epoch_time = current_time

        print(
            'total time: %4.4f s, epoch_time: %4.4f s, epoch: [%d/%d], learning_rate: %.7f'
              %
            (total_time, epoch_time, epoch, self.ed_epoch-1, self.lr), end=''
        )

        self.train_log = open(os.path.join(self.ckpt_path, 'train_log.txt'), 'a')
        self.train_log.write(
            'total time: %4.4f s, epoch_time: %4.4f s, epoch: [%d/%d], learning_rate: %.7f'
              %
            (total_time, epoch_time, epoch, self.ed_epoch-1, self.lr)
        )

        for label in self.state_dict.keys():
            print(', %s: %.7f' % (label, self.state_dict[label]), end='')
            self.train_log.write(', %s: %.7f' % (label, self.state_dict[label]))
        print('')
        self.train_log.write('\n')
        self.train_log.close()


def get_scheduler(optimizer, opt):
    if opt.lr_policy == 'lambda':
        def lambda_rule(epoch):
            lr_l = 1.0 - max(0, epoch + opt.epoch_count - opt.niter) / float(opt.niter_decay + 1)
            return lr_l
        scheduler = optim.lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda_rule)
    elif opt.lr_policy == 'step':
        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=opt.lr_decay_iters, gamma=0.1)
    elif opt.lr_policy == 'plateau':
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.2, threshold=0.01, patience=5)
    elif opt.lr_policy == 'cosine':
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=opt.niter, eta_min=0)
    else:
        return NotImplementedError('learning rate policy [%s] is not implemented', opt.lr_policy)
    return scheduler
