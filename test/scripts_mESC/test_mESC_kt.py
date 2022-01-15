# In[0]
import sys, os
sys.path.append('../../src/')

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
import time
import gc
import torch
import torch.nn
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.manifold import MDS
from umap import UMAP

import bmk_beeline as bmk
import genie3, g_admm, kernel
import warnings
warnings.filterwarnings("ignore")

from os.path import exists

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
plt.rcParams["font.size"] = 20

def preprocess(counts): 
    """\
    Input:
    counts = (ntimes, ngenes)
    
    Description:
    ------------
    Preprocess the dataset
    """
    # normalize according to the library size
    
    libsize = np.median(np.sum(counts, axis = 1))
    counts = counts / np.sum(counts, axis = 1)[:,None] * libsize
        
    counts = np.log1p(counts)
    return counts

# In[1]
path = "../../data/mESC/"
result_dir = "../results_mESC/"

counts = pd.read_csv(path + "counts.csv", index_col = 0).values
annotation = pd.read_csv(path + "anno.csv", index_col = 0)
genes = pd.read_csv(path + "counts.csv", index_col = 0).columns.values
tfs = ['Pou5f1', 'Nr5a2', 'Sox2', 'Sall4', 'Otx2', 'Esrrb', 'Stat3','Tcf7', 'Nanog', 'Etv5']
tf_ids = np.array([np.where(genes == x)[0][0] for x in tfs])

ncells, ngenes = counts.shape
# assert ncells == 8 * 120
assert ngenes == 96
print("Raw TimePoints: {}, no.Genes: {}".format(counts.shape[0],counts.shape[1]))

# check distribution
fig = plt.figure(figsize = (10,7))
ax = fig.add_subplot()
_ = ax.hist(counts.reshape(-1), bins = 20)
fig = plt.figure(figsize = (10,7))
ax = fig.add_subplot()
# counts is already preprocessed
# _ = ax.hist(np.log1p(counts.reshape(-1)), bins = 20)
_ = ax.hist(counts.reshape(-1), bins = 20)

# libsize = np.median(np.sum(counts, axis = 1))
# counts = counts / np.sum(counts, axis = 1)[:,None] * libsize
# # the distribution of the original count is log-normal distribution, conduct log transform
# counts = np.log1p(counts)

pca_op = PCA(n_components = 20)
umap_op = UMAP(n_components = 2, min_dist = 0.8, random_state = 0)

X_pca = pca_op.fit_transform(counts)
X_umap = umap_op.fit_transform(counts)

fig = plt.figure(figsize  = (10,7))
ax = fig.add_subplot()
for i in np.sort(np.unique(annotation.values.squeeze())):
    idx = np.where(annotation.values.squeeze() == i)
    ax.scatter(X_pca[idx, 0], X_pca[idx, 1], label = i)

ax.set_xlabel("PCA1")
ax.set_ylabel("PCA2")
ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False)
fig.savefig(result_dir + "X_pca.png", bbox_inches = "tight")

fig = plt.figure(figsize  = (10,7))
ax = fig.add_subplot()
for i in np.sort(np.unique(annotation.values.squeeze())):
    idx = np.where(annotation.values.squeeze() == i)
    ax.scatter(X_umap[idx, 0], X_umap[idx, 1], label = i)

ax.set_xlabel("UMAP1")
ax.set_ylabel("UMAP2")
ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False)
fig.savefig(result_dir + "X_umap.png", bbox_inches = "tight")

# X = torch.FloatTensor(counts).to(device)

# In[2] ADMM
# hyper-parameter
bandwidths = [0.1, 1, 10]
truncate_params = [400, 1000, 2000]
lambs = [0.001, 0.01, 0.05, 0.1]
assert len(sys.argv) == 3

# for bandwidth in [bandwidths[eval(sys.argv[1])]]:
#     for truncate_param in [truncate_params[eval(sys.argv[2])]]:
#         # calculate empirical covariance matrix
#         start_time = time.time()
#         empir_cov = torch.zeros(ncells, ngenes, ngenes)
#         # calculate the kernel function
#         K, K_trun = kernel.calc_kernel_neigh(X_pca, k = 5, bandwidth = bandwidth, truncate = True, truncate_param = truncate_param)

#         # plot kernel function
#         fig = plt.figure(figsize = (20, 7))
#         axs = fig.subplots(1, 2)
#         axs[0].plot(K[int(ncells/2), :])
#         axs[1].plot(K_trun[int(ncells/2), :])
#         fig.suptitle("kernel_" + str(bandwidth) + "_" + str(truncate_param))
#         fig.savefig(result_dir + "plots/kernel_" + str(bandwidth) + "_" + str(truncate_param) + ".png", bbox_inches = "tight")

#         fig = plt.figure(figsize  = (10,7))
#         ax = fig.add_subplot()
#         ax.scatter(X_pca[:, 0], X_pca[:, 1], c = K[int(ncells/2), :])

#         ax.set_xlabel("PCA1")
#         ax.set_ylabel("PCA2")
#         ax.set_title("kernel_" + str(bandwidth))
#         fig.savefig(result_dir + "plots/kernel_" + str(bandwidth) + "_pca.png", bbox_inches = "tight")

#         fig = plt.figure(figsize  = (10,7))
#         ax = fig.add_subplot()
#         ax.scatter(X_umap[:, 0], X_umap[:, 1], c = K[int(ncells/2), :])

#         ax.set_xlabel("UMAP1")
#         ax.set_ylabel("UMAP1")
#         ax.set_title("kernel_" + str(bandwidth))
#         fig.savefig(result_dir + "plots/kernel_" + str(bandwidth) + "_umap.png", bbox_inches = "tight")


#         print("number of neighbor being considered: " + str(np.sum(K_trun[int(ncells/2), :] > 0)))

#         # building weighted covariance matrix, output is empir_cov of the shape (ncells, ngenes, ngenes)
#         empir_cov = g_admm.est_cov(X = counts, K_trun = K_trun, weighted_kt = True)

#         for lamb in lambs:
#             alpha = 2
#             rho = 1.7
#             max_iters = 1000

#             if exists(result_dir + "thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_kt.npy"):
#                 continue 
#             else:
#                 start_time = time.time() 
#                 # test model without TF
#                 thetas = np.zeros((ncells, ngenes, ngenes))

#                 # gadmm_batch = g_admm.G_admm_batch(X=X[:, None, :], K=K, pre_cov=empir_cov)
#                 gadmm_batch = g_admm.G_admm_minibatch(X=counts[:, None, :], K=K, pre_cov=empir_cov, batchsize = 120)
#                 thetas = gadmm_batch.train(max_iters=max_iters, n_intervals=100, alpha=alpha, lamb=lamb, rho=rho, theta_init_offset=0.1)
#                 np.save(file = result_dir + "thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_kt.npy", arr = thetas) 
#                 print("time calculating thetas: {:.2f} sec".format(time.time() - start_time))

#                 thetas = thetas.reshape(thetas.shape[0], -1)
#                 thetas_pca = pca_op.fit_transform(thetas)
#                 thetas_umap = umap_op.fit_transform(thetas)

#                 fig = plt.figure(figsize  = (10,7))
#                 ax = fig.add_subplot()
#                 for i in np.sort(np.unique(annotation.values.squeeze())):
#                     idx = np.where(annotation.values.squeeze() == i)
#                     ax.scatter(thetas_pca[idx, 0], thetas_pca[idx, 1], label = i, s = 10)
#                 ax.set_xlabel("PCA1")
#                 ax.set_ylabel("PCA2")
#                 ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False, markerscale = 3)
#                 ax.set_title("bandwidth: " + str(bandwidth) + ", truncate_param: " + str(truncate_param) + ", lamb: " + str(lamb))
#                 fig.savefig(result_dir + "plots/thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_0_pca.png", bbox_inches = "tight")

#                 fig = plt.figure(figsize  = (10,7))
#                 ax = fig.add_subplot()
#                 for i in np.sort(np.unique(annotation.values.squeeze())):
#                     idx = np.where(annotation.values.squeeze() == i)
#                     ax.scatter(thetas_umap[idx, 0], thetas_umap[idx, 1], label = i, s = 10)
#                 ax.set_xlabel("UMAP1")
#                 ax.set_ylabel("UMAP2")
#                 ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False, markerscale = 3)
#                 ax.set_title("bandwidth: " + str(bandwidth) + ", truncate_param: " + str(truncate_param) + ", lamb: " + str(lamb))
#                 fig.savefig(result_dir + "plots/thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_0_umap.png", bbox_inches = "tight")

#                 del thetas
#                 gadmm_batch = None
#                 gc.collect()

# In[]
# test for TF modes
for bandwidth in [bandwidths[eval(sys.argv[1])]]:
    for truncate_param in [truncate_params[eval(sys.argv[2])]]:
        # calculate empirical covariance matrix
        start_time = time.time()
        empir_cov = torch.zeros(ncells, ngenes, ngenes)
        # calculate the kernel function
        K, K_trun = kernel.calc_kernel_neigh(X_pca, k = 5, bandwidth = bandwidth, truncate = True, truncate_param = truncate_param)

        # plot kernel function
        fig = plt.figure(figsize = (20, 7))
        axs = fig.subplots(1, 2)
        axs[0].plot(K[int(ncells/2), :])
        axs[1].plot(K_trun[int(ncells/2), :])
        fig.suptitle("kernel_" + str(bandwidth) + "_" + str(truncate_param))
        fig.savefig(result_dir + "plots/kernel_" + str(bandwidth) + "_" + str(truncate_param) + ".png", bbox_inches = "tight")

        fig = plt.figure(figsize  = (10,7))
        ax = fig.add_subplot()
        ax.scatter(X_pca[:, 0], X_pca[:, 1], c = K[int(ncells/2), :])

        ax.set_xlabel("PCA1")
        ax.set_ylabel("PCA2")
        ax.set_title("kernel_" + str(bandwidth))
        fig.savefig(result_dir + "plots/kernel_" + str(bandwidth) + "_pca.png", bbox_inches = "tight")

        fig = plt.figure(figsize  = (10,7))
        ax = fig.add_subplot()
        ax.scatter(X_umap[:, 0], X_umap[:, 1], c = K[int(ncells/2), :])

        ax.set_xlabel("UMAP1")
        ax.set_ylabel("UMAP1")
        ax.set_title("kernel_" + str(bandwidth))
        fig.savefig(result_dir + "plots/kernel_" + str(bandwidth) + "_umap.png", bbox_inches = "tight")


        print("number of neighbor being considered: " + str(np.sum(K_trun[int(ncells/2), :] > 0)))

        # building weighted covariance matrix, output is empir_cov of the shape (ncells, ngenes, ngenes)
        empir_cov = g_admm.est_cov(X = counts, K_trun = K_trun, weighted_kt = True)

        for lamb in lambs:
            alpha = 2
            rho = 1.7
            max_iters = 1000
            for beta in [100]:
                if exists(result_dir + "thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_" + str(beta) + "_kt.npy"):
                    continue 
                else:
                    start_time = time.time() 
                    # test model without TF
                    thetas = np.zeros((ncells, ngenes, ngenes))

                    # gadmm_batch = g_admm.G_admm_batch(X=X[:, None, :], K=K, pre_cov=empir_cov)
                    gadmm_batch = g_admm.G_admm_minibatch(X=counts[:, None, :], K=K, pre_cov=empir_cov, batchsize = 120, TF = tf_ids)
                    thetas = gadmm_batch.train(max_iters=max_iters, n_intervals=100, alpha=alpha, lamb=lamb, rho=rho, beta = beta, theta_init_offset=0.1)
                    np.save(file = result_dir + "thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_" + str(beta) +  "_kt.npy", arr = thetas) 
                    print("time calculating thetas: {:.2f} sec".format(time.time() - start_time))

                    thetas = thetas.reshape(thetas.shape[0], -1)
                    thetas_pca = pca_op.fit_transform(thetas)
                    thetas_umap = umap_op.fit_transform(thetas)

                    fig = plt.figure(figsize  = (10,7))
                    ax = fig.add_subplot()
                    for i in np.sort(np.unique(annotation.values.squeeze())):
                        idx = np.where(annotation.values.squeeze() == i)
                        ax.scatter(thetas_pca[idx, 0], thetas_pca[idx, 1], label = i, s = 10)
                    ax.set_xlabel("PCA1")
                    ax.set_ylabel("PCA2")
                    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False, markerscale = 3)
                    ax.set_title("bandwidth: " + str(bandwidth) + ", truncate_param: " + str(truncate_param) + ", lamb: " + str(lamb))
                    fig.savefig(result_dir + "plots/thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param) + "_" + str(beta) + "_pca.png", bbox_inches = "tight")

                    fig = plt.figure(figsize  = (10,7))
                    ax = fig.add_subplot()
                    for i in np.sort(np.unique(annotation.values.squeeze())):
                        idx = np.where(annotation.values.squeeze() == i)
                        ax.scatter(thetas_umap[idx, 0], thetas_umap[idx, 1], label = i, s = 10)
                    ax.set_xlabel("UMAP1")
                    ax.set_ylabel("UMAP2")
                    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False, markerscale = 3)
                    ax.set_title("bandwidth: " + str(bandwidth) + ", truncate_param: " + str(truncate_param) + ", lamb: " + str(lamb))
                    fig.savefig(result_dir + "plots/thetas_" + str(bandwidth) + "_" + str(lamb) + "_" + str(truncate_param)  + "_" + str(beta) + "_umap.png", bbox_inches = "tight")

                    del thetas
                    gadmm_batch = None
                    gc.collect()


# In[]
# GENIE3
genie_theta = genie3.GENIE3(counts, gene_names=[x for x in genes], regulators='all',tree_method='RF',K='sqrt',ntrees=1000,nthreads=1)
genie_theta = np.repeat(genie_theta[None, :, :], ncells, axis=0)
np.save(file = result_dir + "theta_genie.npy", arr = genie_theta)

genie_theta = genie3.GENIE3(counts, gene_names=[x for x in genes], regulators = tfs, tree_method='RF',K='sqrt',ntrees=1000,nthreads=1)
genie_theta = np.repeat(genie_theta[None, :, :], ncells, axis=0)
np.save(file = result_dir + "theta_genie_tfs.npy", arr = genie_theta)
# # In[]
# import importlib
# importlib.reload(g_admm)
# # Single GGM
# lamb = 0.005
# alpha = 2
# rho = 1.7
# max_iters = 1000

# gadmm_batch = g_admm.G_admm_batch(X=counts[None, :, :], K=torch.FloatTensor([1])[:, None], pre_cov=None)
# thetas = gadmm_batch.train(max_iters=max_iters, n_intervals=100, alpha=alpha, lamb=lamb, rho=rho, theta_init_offset=0.1)
# np.save(file = result_dir + "theta_static.npy", arr = thetas)

# %%
