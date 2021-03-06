import torch
import numpy as np
import os
import random
import math
import torch.nn.functional as F
import torch.nn as nn

# e2efold
from models.e2efold.models import ContactNetwork, ContactNetwork_test, ContactNetwork_fc
from models.e2efold.models import ContactAttention, ContactAttention_simple_fix_PE
from models.e2efold.models import Lag_PP_NN, RNA_SS_e2e, Lag_PP_zero, Lag_PP_perturb, Lag_PP_mixed
from models.e2efold.models import ContactAttention_simple

# mxfold2
from models.mxfold2.fold.mix import MixedFold
from models.mxfold2.fold.rnafold import RNAFold
from models.mxfold2.fold.zuker import ZukerFold

def set_seed(seed):
    os.environ['PYTHONHASHSEED'] = str(seed)
    torch.manual_seed(seed)
    if (torch.cuda.is_available()):
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed) # if you are using multi-GPU.
    random.seed(seed)
    np.random.seed(seed)
    # try:
    #     torch.use_deterministic_algorithms(True)
    # except:
    #     pass
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def build_model(args):
    model_name = args.model
    if model_name == 'mxfold2':
        config = {
            'max_helix_length': args.max_helix_length,
            'embed_size' : args.embed_size,
            'num_filters': args.num_filters if args.num_filters is not None else (96,),
            'filter_size': args.filter_size if args.filter_size is not None else (5,),
            'pool_size': args.pool_size if args.pool_size is not None else (1,),
            'dilation': args.dilation, 
            'num_lstm_layers': args.num_lstm_layers, 
            'num_lstm_units': args.num_lstm_units,
            'num_transformer_layers': args.num_transformer_layers,
            'num_transformer_hidden_units': args.num_transformer_hidden_units,
            'num_transformer_att': args.num_transformer_att,
            'num_hidden_units': args.num_hidden_units if args.num_hidden_units is not None else (32,),
            'num_paired_filters': args.num_paired_filters,
            'paired_filter_size': args.paired_filter_size,
            'dropout_rate': args.dropout_rate,
            'fc_dropout_rate': args.fc_dropout_rate,
            'num_att': args.num_att,
            'pair_join': args.pair_join,
            'no_split_lr': args.no_split_lr,
        }
        
        if args.model_type is None or args.model_type == 'Turner':
            return RNAFold()
        elif args.model_type == 'Zuker':
            return ZukerFold(model_type='M', **config)

        elif args.model_type == 'ZukerC':
            return ZukerFold(model_type='C', **config)

        elif args.model_type == 'ZukerL':
            return ZukerFold(model_type="L", **config)

        elif args.model_type == 'ZukerS':
            return ZukerFold(model_type="S", **config)

        elif args.model_type == 'Mix':
            from models.mxfold2 import param_turner2004
            return MixedFold(init_param=param_turner2004, **config)

        elif args.model_type == 'MixC':
            from models.mxfold2 import param_turner2004
            return MixedFold(init_param=param_turner2004, model_type='C', **config)
        
        else:
            raise NotImplementedError(f'mxfold2-{args.model_type} is not yet implemented.')
        
    elif model_name == 'e2efold':
        d = args.u_net_d
        seq_len = args.seq_max_len
        print("mxlen", args.seq_max_len)
        if args.model_type =='test_lc':
            contact_net =  ContactNetwork_test(d=d, L=seq_len)
        elif args.model_type == 'att6':
            contact_net =  ContactAttention(d=d, L=seq_len)
        elif args.model_type == 'att_simple':
            contact_net =  ContactAttention_simple(d=d, L=seq_len)    
        elif args.model_type is None or args.model_type == 'att_simple_fix':
            contact_net =  ContactAttention_simple_fix_PE(d=d, L=seq_len)
        elif args.model_type == 'fc':
            contact_net = ContactNetwork_fc(d=d, L=seq_len)
        elif args.model_type == 'conv2d_fc':
            contact_net =  ContactNetwork(d=d, L=seq_len)
        else:
            raise NotImplementedError(f'e2efold-{args.model_type} is not yet implemented.')

        pp_steps = args.pp_steps
        k = args.k
        rho_per_position = args.rho_per_position
        pp_type = '{}_s{}'.format(args.pp_model, pp_steps)
        if pp_type=='nn':
            lag_pp_net = Lag_PP_NN(pp_steps, k)
        elif 'zero' in pp_type:
            lag_pp_net = Lag_PP_zero(pp_steps, k)
        elif 'perturb' in pp_type:
            lag_pp_net = Lag_PP_perturb(pp_steps, k)
        elif 'mixed'in pp_type:
            lag_pp_net = Lag_PP_mixed(pp_steps, k, rho_per_position)
        else:
            raise NotImplementedError(f'e2efold-{pp_type} is not yet implemented.')
        
        rna_ss_e2e = RNA_SS_e2e(contact_net, lag_pp_net)

        if args.e2e_load != "":
            if os.path.isfile(args.e2e_load):
                print(f'Loading e2e model from {args.e2e_load}')
                rna_ss_e2e.load_state_dict(torch.load(args.e2e_load), strict = True)

        return rna_ss_e2e 
        
    else:
        raise NotImplementedError(f'Model {model_name} is not yet implemented.')


def save_model(model, epoch, args):
    save_dir = os.path.join(args.log_dir, args.model+'_'+args.exp)
    if( not os.path.exists(args.log_dir) ):
        os.mkdir(args.log_dir)
    if( not os.path.exists(save_dir) ):
        os.mkdir(save_dir)
    save_path = os.path.join(save_dir,  str(epoch)+'.pth')
    torch.save(model.state_dict(), save_path)


def load_model(model, epoch, args):
    save_path = os.path.join(args.log_dir, args.model+'_'+args.exp, str(epoch)+'.pth')
    if (not torch.cuda.is_available()) or args.device == 'cpu':
        model.load_state_dict(torch.load(save_path, map_location=torch.device('cpu')))
    else:
        model.load_state_dict(torch.load(save_path, map_location=torch.device('gpu')))

# Model specific

#! Untested
def p2contact(seq_max_len, pairs):
    '''
    Convert from mxfold2.pair to e2efold.contact
    
    Args:
        pairs (list(int)): mxfold2.pair to convert
    '''
    seq_len = seq_max_len
    contact = torch.zeros([seq_len, seq_len])
    for i in range(len(pairs)):
        if pairs[i] != 0:
            contact[i, pairs[i]-1] = 1
    return contact

encoding_dict = {
    '.':np.array([0,0,0,0]),
    'A':np.array([1,0,0,0]),
    'U':np.array([0,1,0,0]),
    'C':np.array([0,0,1,0]),
    'G':np.array([0,0,0,1]),
    'N':np.array([0,0,0,0]),
    'M':np.array([1,0,1,0]),
    'Y':np.array([0,1,1,0]),
    'W':np.array([1,0,0,0]),
    'V':np.array([1,0,1,1]),
    'K':np.array([0,1,0,1]),
    'R':np.array([1,0,0,1]),
    'I':np.array([0,0,0,0]),
    'X':np.array([0,0,0,0]),
    'S':np.array([0,0,1,1]),
    'D':np.array([1,1,0,1]),
    'P':np.array([0,0,0,0]),
    'B':np.array([0,1,1,1]),
    'H':np.array([1,1,1,0]),
    
    #! 'T' is equivalent to 'U' (?)
    #* TestSetA/180.bpseq
    #* TestSetA/184.bpseq
    'T':np.array([0,1,0,0]),
    
    #! lower cases equivalent to upper cases (?)
    #* bpRNA_dataset-canonicals/TR0/bpRNA_CRW_54549.bpseq
    'a':np.array([1,0,0,0]),
    'u':np.array([0,1,0,0]),
    'c':np.array([0,0,1,0]),
    'g':np.array([0,0,0,1]),
    'n':np.array([0,0,0,0]),
    'm':np.array([1,0,1,0]),
    'y':np.array([0,1,1,0]),
    'w':np.array([1,0,0,0]),
    'v':np.array([1,0,1,1]),
    'k':np.array([0,1,0,1]),
    'r':np.array([1,0,0,1]),
    'i':np.array([0,0,0,0]),
    'x':np.array([0,0,0,0]),
    's':np.array([0,0,1,1]),
    'd':np.array([1,1,0,1]),
    'p':np.array([0,0,0,0]),
    'b':np.array([0,1,1,1]),
    'h':np.array([1,1,1,0]),
}

#* Tested
def seq2encoding(seq_max_len, seq):
    '''
    Convert from mxfold2.seq to e2efold.data_x
    
    Args:
        seq (str): mxfold2.seq to convert
    '''
    s = list(seq)
    enc = list(map(lambda c: encoding_dict[c], s))
    #! shouldn't use torch.Tensor.resize()
    #! because new elements are uninitialized
    enc = np.stack(enc, axis=0)
    enc.resize((seq_max_len, 4))
    return enc

def get_pe(seq_lens, max_len):
    num_seq = seq_lens.shape[0]
    pos_i_abs = torch.Tensor(np.arange(1,max_len+1)).view(1, 
        -1, 1).expand(num_seq, -1, -1).double()
    pos_i_rel = torch.Tensor(np.arange(1,max_len+1)).view(1, -1).expand(num_seq, -1)
    pos_i_rel = pos_i_rel.double()/seq_lens.view(-1, 1).double()
    pos_i_rel = pos_i_rel.unsqueeze(-1)
    pos = torch.cat([pos_i_abs, pos_i_rel], -1)

    PE_element_list = list()
    # 1/x, 1/x^2
    PE_element_list.append(pos)
    PE_element_list.append(1.0/pos_i_abs)
    PE_element_list.append(1.0/torch.pow(pos_i_abs, 2))

    # sin(nx)
    for n in range(1, 50):
        PE_element_list.append(torch.sin(n*pos))

    # poly
    for i in range(2, 5):
        PE_element_list.append(torch.pow(pos_i_rel, i))

    for i in range(3):
        gaussian_base = torch.exp(-torch.pow(pos, 
            2))*math.sqrt(math.pow(2,i)/math.factorial(i))*torch.pow(pos, i)
        PE_element_list.append(gaussian_base)

    PE = torch.cat(PE_element_list, -1)
    for i in range(num_seq):
        PE[i, seq_lens[i]:, :] = 0
    return PE

def contact_map_masks(seq_lens, max_len):
    n_seq = len(seq_lens)
    masks = np.zeros([n_seq, max_len, max_len])
    for i in range(n_seq):
        l = int(seq_lens[i].cpu().numpy())
        masks[i, :l, :l]=1
    return masks

# e2e specific

def f1_loss(pred_a, true_a):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pred_a  = -(F.relu(-pred_a+1)-1)

    true_a = true_a.unsqueeze(1)
    unfold = nn.Unfold(kernel_size=(3, 3), padding=1)
    true_a_tmp = unfold(true_a)
    w = torch.Tensor([0, 0.0, 0, 0.0, 1, 0.0, 0, 0.0, 0]).to(device)
    true_a_tmp = true_a_tmp.transpose(1, 2).matmul(w.view(w.size(0), -1)).transpose(1, 2)
    true_a = true_a_tmp.view(true_a.shape)
    true_a = true_a.squeeze(1)

    tp = pred_a*true_a
    tp = torch.sum(tp, (1,2))

    fp = pred_a*(1-true_a)
    fp = torch.sum(fp, (1,2))

    fn = (1-pred_a)*true_a
    fn = torch.sum(fn, (1,2))

    f1 = torch.div(2*tp, (2*tp + fp + fn))
    return 1-f1.mean()


def pairs2dot_bracket(pairs):
    result = ""
    for i in range(1, len(pairs)):
        if pairs[i] == 0:
            result += '.'
        elif pairs[i] > i:
            result += '('
        else:
            result += ')'
    return result