import torch
import torch.nn as nn
#from utility import *
import torch.nn.functional as F
import numpy as np
import math


class MXEdge(nn.Module):
    def __init__(self,device='cuda',in_dim = 128, out_dim = 64,T=9,num_mod = 6,mod_dim = 32,mod_out_dim = 8):
        super(MXEdge,self).__init__()
        #a bit of the hack to create a faster version of the multiplex edge.
        #Forcing a linear layer to have K sub-groups corrresponding to K sub-edges.
        self.num_mod = num_mod
        self.mod_dim = mod_dim
        self.mod_out_dim = mod_out_dim
        self.device = device
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.T = T
        self.mod_layer_1 = nn.Linear(self.in_dim,self.mod_dim*self.num_mod)
        self.mod_layer_1_bn = nn.BatchNorm1d(self.mod_dim*self.num_mod)
       
        self.m_w_1 = nn.Parameter(torch.rand(self.mod_dim*self.num_mod,self.mod_out_dim*self.num_mod),requires_grad=True)
        self.m_b_1 = nn.Parameter(torch.zeros(self.mod_out_dim*self.num_mod),requires_grad=True)
        self.m_w_1,self.m_b_1 = self.init_w(self.m_w_1,self.m_b_1)
        self.m_w_1_mask = self.create_mask(self.m_w_1)

        self.m_bn_1 = nn.BatchNorm1d(self.mod_out_dim*self.num_mod)
        self.relu = nn.ReLU(True)
                              
                           
        self.mplx_attn = nn.Linear(3*self.num_mod*self.mod_out_dim,3*self.num_mod)

        self.rel_local_fc_1 = nn.Linear(self.num_mod*self.mod_out_dim*2*3,self.out_dim)
        self.rel_local_fc_1_bn = nn.BatchNorm1d(self.out_dim)

    def init_w(self,w,b):
        stdv = 1. / math.sqrt(w.size(1))
        w.data.uniform_(-stdv, stdv)
        b.data.uniform_(-stdv, stdv)
        return w,b

    def create_mask(self,w):
        w_mask = torch.zeros_like(w)
        chunk_0_size = w.size(0)//self.num_mod
        chunk_1_size = w.size(1)//self.num_mod
        for i in range(self.num_mod):
            w_mask[chunk_0_size*i:chunk_0_size*(i+1),chunk_1_size*i:chunk_1_size*(i+1)]=1
        return nn.Parameter(w_mask,requires_grad=False)

    def linear_func(self,x,w,b,m):
        w = w*m
        o = torch.mm(x,w)
        o = o + b.unsqueeze(0).expand_as(o)
        return o

    def module_net(self,x):
        x = self.linear_func(x,self.m_w_1,self.m_b_1,self.m_w_1_mask)
        x = self.m_bn_1(x)
        x = self.relu(x)
        return x

    def set_summarize(self,x,axis):
        x_sum = torch.sum(x,axis)
        x_mean = torch.mean(x,axis)
        x_max,_ = torch.max(x,axis)

        return torch.cat([x_sum,x_mean,x_max],1)


    def forward(self,fl_02,fl_12):
        fm_02 = F.relu(self.mod_layer_1_bn(self.mod_layer_1(fl_02.view(-1,self.in_dim))))
        fm_12 = F.relu(self.mod_layer_1_bn(self.mod_layer_1(fl_12.view(-1,self.in_dim))))
        fm_02 = self.module_net(fm_02)
        fm_12 = self.module_net(fm_12)

        fm_02_sum = self.set_summarize(fm_02.view(-1,self.T,self.num_mod*self.mod_out_dim),1)
        fm_12_sum = self.set_summarize(fm_12.view(-1,self.T,self.num_mod*self.mod_out_dim),1)

        fm_02_attn = F.sigmoid(self.mplx_attn(fm_02_sum)).unsqueeze(2).repeat(1,1,self.mod_out_dim).view(-1,3*self.num_mod*self.mod_out_dim)
        fm_12_attn = F.sigmoid(self.mplx_attn(fm_12_sum)).unsqueeze(2).repeat(1,1,self.mod_out_dim).view(-1,3*self.num_mod*self.mod_out_dim)

        fm_02_sum = fm_02_sum * fm_02_attn
        fm_12_sum = fm_12_sum * fm_12_attn

        fm_cat = torch.cat([fm_02_sum,fm_12_sum],1)
        fl = F.relu(self.rel_local_fc_1_bn(self.rel_local_fc_1(fm_cat)))
        return fl
