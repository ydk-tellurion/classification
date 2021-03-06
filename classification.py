import torch
import torch.nn as nn
import torch.optim as optim
import itertools

import os
import json
import numpy as np

from models import *

class classifier(BaseModel):
    eps = 1e-7

    def __init__(self, opt):
        super(classifier, self).__init__(opt)
        self.initialize()

    def initialize(self):
        self.opt_model = 'classificiation'
        self.device = torch.device(self.opt.device)
        if self.opt.model == 'resnet50':
            self.model = resnet.resnet50(num_classes=self.num_classes,
                                pretrained_model=self.opt.pretrained_model).to(self.device)
        elif self.opt.model == 'resnet34':
            self.model = resnet.resnet34(num_classes=self.num_classes,
                                pretrained_model=self.opt.pretrained_model).to(self.device)
        elif self.opt.model == 'resnext50':
            self.model = resnet.resnet50_32x4d(num_classes=self.num_classes,
                                               pretrained_model=self.opt.pretrained_model).to(self.device)
        elif self.opt.model == 'senet50':
            self.model = senet.legacy_seresnet50(num_classes=self.num_classes,
                                                 pretrained_model=self.opt.pretrained_model).to(self.device)
        elif self.opt.model == 'senext50':
            self.model = senet.legacy_seresnext50_32x4d(num_classes=self.num_classes,
                                                        pretrained_model=self.opt.pretrained_model).to(self.device)
        else:
            raise NotImplementedError('Such model is not implemented.')


        if not self.opt.eval:
            if self.opt.optimizer == 'sgd':
                self.optimizer = optim.SGD(self.model.parameters(), lr=self.lr,
                                           momentum=self.momentum)
            elif self.opt.optimizer == 'adam':
                self.optimizer = optim.Adam(self.model.parameters(), lr=self.lr,
                                            betas=self.betas)
            else:
                raise NotImplementedError('Such optimizer is not implemented.')

            if self.opt.loss == 'focal':
                self.criterion = FocalLoss(alpha=0.2, gamma=2)
            else:
                weights = None
                if self.opt.reweight:
                    with open('tag_utils/tag_weights.json', 'r') as file:
                        weights = torch.Tensor(json.load(file))[: self.num_classes].to(self.device)
                self.criterion = nn.BCELoss(weight=weights, reduction='sum').to(self.device)
            self.optimizers = [self.optimizer]
        self.models = {'classification': self.model}
        self.setup()

    def read_input(self, input):
        self.x = input['image'].to(self.device)
        self.y = input['class'].to(self.device)

    def forward(self):
        self.predict_y = self.model(self.x)

    def backward(self):
        self.loss = self.criterion(self.predict_y, self.y) / self.batch_size
        self.loss.backward()

    def train(self):
        self.step = self.opt.start_step
        if self.opt.load_model:
            self.load(self.opt.load_epoch)

        for epoch in range(self.st_epoch, self.ed_epoch):
            for idx, data in enumerate(self.datasets):
                self.read_input(data)

                self.optimizer.zero_grad()
                self.forward()
                self.backward()
                self.optimizer.step()

                if idx % self.opt.print_state_freq == 0:
                    self.set_state_dict()
                    self.print_training_iter(epoch, idx)
                if idx % self.opt.save_model_freq_step == 0:
                    self.save()

                self.step += 1

            self.save()
            self.set_state_dict()
            self.print_training_epoch(epoch)

            if epoch % self.opt.save_model_freq == 0:
                self.save(epoch)

            for scheduler in self.schedulers:
                scheduler.step()


    def calc_accuracy(self):
        predict_y = self.predict_y.detach()
        predict_y[predict_y < self.opt.score_thres] = 0.
        predict_y[predict_y >= self.opt.score_thres] = 1.

        gt_y = self.y.detach()
        truth_value = predict_y + gt_y * 2.
        tn = truth_value.eq(0.).sum().float()
        fp = truth_value.eq(1.).sum().float()
        fn = truth_value.eq(2.).sum().float()
        tp = truth_value.eq(3.).sum().float()

        self.accuracy = tp / (tp + fp + fn + self.eps)
        self.precision = tp / (tp + fp + self.eps)
        self.recall = tp / (tp + fn + self.eps)
        self.micro_F2 = (5. * self.precision * self.recall) / (self.recall + 4 * self.precision + self.eps)


    def set_state_dict(self, eval=False):
        with torch.no_grad():
            self.calc_accuracy()

        if not eval:
            self.state_dict = {'loss': self.loss, 'accuracy': self.accuracy,
                               'precision': self.precision, 'recall': self.recall, 'micro-F2-score': self.micro_F2}
        else:
            self.state_dict = {'accuracy': self.accuracy, 'precision': self.precision,
                               'recall': self.recall, 'micro-F2-score': self.micro_F2}


    # evaluation mode
    def test(self):
        with torch.no_grad():
            self.model.eval()
            state_dict = torch.load(os.path.join(self.ckpt_path,
                                                 self.opt.load_epoch + '_classification_params.pth'))
            self.model.load_state_dict(state_dict)
            with open('tag_utils/tag_index.json', 'r') as f:
                tag_dict = json.load(f)
            for idx, data in enumerate(self.datasets):
                if self.opt.gt_label:
                    self.read_input(data)
                else:
                    self.x = data['image'].to(self.device)
                self.forward()
                predict = np.array(self.predict_y[0].cpu())
                indices  = np.argsort(-predict)

                print('image file: {}\nprediction labels:'.format(data['path']))
                for i in indices:
                    if predict[i] < self.opt.score_thres:
                        break
                    print('{}: {:.4f}, '.format(tag_dict[str(i)], predict[i]), end='')

                if self.opt.gt_label:
                    y_indices = np.argsort(-np.array(self.y[0].cpu()))
                    print('\nground truth labels:')
                    for i in y_indices:
                        if self.y[0][i] < 1.:
                            break
                        print('{}, '.format(tag_dict[str(i)]), end='')

                    print('\nEvaluation score')
                    self.set_state_dict(True)
                    for key in self.state_dict.keys():
                        print('{}: {}'.format(key, self.state_dict[key]))
                print()
