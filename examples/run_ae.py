'''
@Author: Yu Di
@Date: 2019-12-05 10:41:50
@LastEditors  : Yudi
@LastEditTime : 2019-12-23 15:05:23
@Company: Cardinal Operation
@Email: yudi@shanshu.ai
@Description: 
'''
import os
import random
import argparse
import numpy as np
import pandas as pd
from tqdm import tqdm
from collections import defaultdict

import torch
import torch.utils.data as data

from daisy.model.AERecommender import AE
from daisy.utils.loader import load_rate, split_test, get_ur, AEData
from daisy.utils.metrics import precision_at_k, recall_at_k, map_at_k, hr_at_k, mrr_at_k, ndcg_at_k

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AutoEncoder recommender test')
    # common settings
    parser.add_argument('--dataset', 
                        type=str, 
                        default='ml-100k', 
                        help='select dataset')
    parser.add_argument('--prepro', 
                        type=str, 
                        default='origin', 
                        help='dataset preprocess op.: origin/5core/10core')
    parser.add_argument('--topk', 
                        type=int, 
                        default=50, 
                        help='top number of recommend list')
    parser.add_argument('--test_method', 
                        type=str, 
                        default='fo', 
                        help='method for split test,options: loo/fo/tfo/tloo')
    parser.add_argument('--test_size', 
                        type=float, 
                        default=.2, 
                        help='split ratio for test set')
    parser.add_argument('--val_method', 
                        type=str, 
                        default='loo', 
                        help='validation method, options: cv, tfo, loo, tloo')
    parser.add_argument('--fold_num', 
                        type=int, 
                        default=5, 
                        help='No. of folds for cross-validation')
    parser.add_argument('--cand_num', 
                        type=int, 
                        default=1000, 
                        help='No. of candidates item for predict')
    # algo settings
    parser.add_argument('--hidden_neuron', 
                        type=int, 
                        default=500, 
                        help='hidden neuron number')
    parser.add_argument('--epochs', 
                        type=int, 
                        default=20, 
                        help='training epochs')
    parser.add_argument('--lr', 
                        type=float, 
                        default=0.01, 
                        help='learning rate')
    parser.add_argument('--lamda', 
                        type=float, 
                        default=1., 
                        help='regularization weight')
    parser.add_argument('--batch_size', 
                        type=int, 
                        default=100, 
                        help='batch size for training')
    parser.add_argument('--gpu', 
                        type=str, 
                        default='0', 
                        help='gpu card ID')
    args = parser.parse_args()

    '''Test Process for Metrics Exporting'''
    df, user_num, item_num = load_rate(args.dataset, args.prepro, binary=False)
    train_set, test_set = split_test(df, args.test_method, args.test_size)

    # get ground truth
    test_ur = get_ur(test_set)
    total_train_ur = get_ur(train_set)

    # initial candidate item pool
    item_pool = set(range(item_num))
    candidates_num = args.cand_num

    print('='*50, '\n')
    # retrain model by the whole train set
    # format training data
    train_dataset = AEData(user_num, item_num, train_set)
    train_loader = data.DataLoader(train_dataset, batch_size=args.batch_size, # 4
                                   shuffle=True, num_workers=4)
    # build recommender model
    model = AE(user_num, item_num, args.hidden_neuron,
               args.epochs, args.lr, args.lamda, args.gpu)
    model.fit(train_loader, train_dataset.R)

    print('Start Calculating Metrics......')
    # build candidates set
    assert max([len(v) for v in test_ur.values()]) < candidates_num, 'Small candidates_num setting'
    test_ucands = defaultdict(list)
    for k, v in test_ur.items():
        sample_num = candidates_num - len(v)
        sub_item_pool = item_pool - v - total_train_ur[k] # remove GT & interacted
        sample_num = min(len(sub_item_pool), sample_num)
        samples = random.sample(sub_item_pool, sample_num)
        test_ucands[k] = list(v | set(samples))

    # get predict result
    print('')
    print('Generate recommend list...')
    print('')
    preds = {}
    for u in tqdm(test_ucands.keys()):
        pred_rates = [model.predict(u, i) for i in test_ucands[u]]
        rec_idx = np.argsort(pred_rates)[::-1][:args.topk]
        top_n = np.array(test_ucands[u])[rec_idx]
        preds[u] = top_n

    # convert rank list to binary-interaction
    for u in preds.keys():
        preds[u] = [1 if i in test_ur[u] else 0 for i in preds[u]]
    
    # calculate metrics for test set
    pre_k = np.mean([precision_at_k(r, args.topk) for r in preds.values()])
    rec_k = recall_at_k(preds, test_ur, args.topk)
    hr_k = hr_at_k(preds, test_ur)
    map_k = map_at_k(preds.values())
    mrr_k = mrr_at_k(preds, args.topk)
    ndcg_k = np.mean([ndcg_at_k(r, args.topk) for r in preds.values()])

    print(f'Precision@{args.topk}: {pre_k:.4f}')
    print(f'Recall@{args.topk}: {rec_k:.4f}')
    print(f'HR@{args.topk}: {hr_k:.4f}')
    print(f'MAP@{args.topk}: {map_k:.4f}')
    print(f'MRR@{args.topk}: {mrr_k:.4f}')
    print(f'NDCG@{args.topk}: {ndcg_k:.4f}')
    print('='* 20, ' Done ', '='*20)

    # process topN list and store result for reporting KPI
    print('Save metric@k result to res folder...')
    result_save_path = f'./res/{args.dataset}/{args.prepro}/{args.test_method}/'
    if not os.path.exists(result_save_path):
        os.makedirs(result_save_path)

    res = pd.DataFrame({'metric@K': ['pre', 'rec', 'hr', 'map', 'mrr', 'ndcg']})

    for k in [1, 5, 10, 20, 30, 50]:
        tmp_preds = preds.copy()        
        tmp_preds = {key: rank_list[:k] for key, rank_list in tmp_preds.items()}

        pre_k = np.mean([precision_at_k(r, k) for r in tmp_preds.values()])
        rec_k = recall_at_k(tmp_preds, test_ur, k)
        hr_k = hr_at_k(tmp_preds, test_ur)
        map_k = map_at_k(tmp_preds.values())
        mrr_k = mrr_at_k(tmp_preds, k)
        ndcg_k = np.mean([ndcg_at_k(r, k) for r in tmp_preds.values()])

        res[k] = np.array([pre_k, rec_k, hr_k, map_k, mrr_k, ndcg_k])

    res.to_csv(f'{result_save_path}metric_result_ae.csv', index=False)