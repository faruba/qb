from functools import lru_cache
from collections import OrderedDict
import re
import sys
import unicodedata
import string

from nltk.corpus import stopwords
from nltk.tokenize.treebank import TreebankWordTokenizer

NEG_INF = float('-inf')
PAREN_EXPRESSION = re.compile(r'\s*\([^)]*\)\s*')
ENGLISH_STOP_WORDS = set(stopwords.words('english'))
QB_STOP_WORDS = {"10", "ten", "points", "tenpoints", "one", "name", ",", ")", "``", "(", '"', ']',
                 '[', ":", "due", "!", "'s", "''", 'ftp'}
STOP_WORDS = ENGLISH_STOP_WORDS | QB_STOP_WORDS
ALPHANUMERIC = re.compile(r'[\W_]+')
PUNCTUATION = string.punctuation
GRANULARITIES = ["sentence"]
FOLDS = ["dev", "devtest", "test"]
FOLDS_NON_NAQT = ["dev", "test"]

LABEL = 'label'
IR = 'ir'
LM = 'lm'
MENTIONS = 'mentions'
DEEP = 'deep'
ANSWER_PRESENT = 'answer_present'
CLASSIFIER = 'classifier'
WIKILINKS = 'wikilinks'

COUNTRY_LIST_PATH = 'data/internal/country_list.txt'

CLM_PATH = 'output/language_model'
CLM_TARGET = 'output/language_model.txt'

DEEP_WE_TARGET = 'output/deep/We'
DEEP_DAN_PARAMS_TARGET = 'output/deep/params'
DEEP_TF_PARAMS_TARGET = 'output/deep/tfparams'
DEEP_DAN_CLASSIFIER_TARGET = 'output/deep/classifier'
DEEP_TRAIN_TARGET = 'output/deep/train'
DEEP_WIKI_TARGET = 'output/deep/wiki'
DEEP_DEV_TARGET = 'output/deep/dev'
DEEP_DAN_TRAIN_OUTPUT = 'output/deep/train_dan'
DEEP_DAN_DEV_OUTPUT = 'output/deep/dev_dan'
DEEP_DEVTEST_TARGET = 'output/deep/devtest'
DEEP_TEST_TARGET = 'output/deep/test'
DEEP_VOCAB_TARGET = 'output/deep/vocab'
EVAL_RES_TARGET = 'output/deep/eval_res'
REPRESENTATION_RES_TARGET = 'output/deep/representations'
REPRESENTATION_TSNE_TARGET = 'output/deep/tsne'

DEEP_EXPERIMENT_FLAG = 'output/deep/experiment_done'
DEEP_EXPERIMENT_S3_BUCKET = 's3://tfexperiments'


DOMAIN_TARGET_PREFIX = 'output/deep/domain_data'
DOMAIN_MODEL_FORMAT = 'output/deep/domain_clf{}.vw'
DOMAIN_PREDICTIONS_PREFIX = 'output/deep/domain_preds'
DOMAIN_OUTPUT = 'output/deep/filtered_domain_data'

WIKIFIER_INPUT_TARGET = 'output/wikifier/input'
WIKIFIER_OUTPUT_TARGET = 'output/wikifier/output'

QB_SOURCE_LOCATION = 'data/internal/source'
NERS_LOCATION = 'data/internal/common/ners'

WHOOSH_WIKI_INDEX_PATH = 'output/whoosh/wiki'
CLASSIFIER_TYPES = ['ans_type', 'category', 'gender']
CLASSIFIER_PICKLE_PATH = 'output/classifier/{0}/{0}.pkl'
CLASSIFIER_REPORT_PATH = 'output/reporting/classifier_{}.pdf'

KEN_LM = 'output/kenlm.binary'

# Do not change order, it matters for writing in correct order
FEATURE_NAMES = [LABEL, LM, MENTIONS, DEEP, ANSWER_PRESENT, CLASSIFIER, WIKILINKS]
NEGATIVE_WEIGHTS = [16]
# NEGATIVE_WEIGHTS = [2, 4, 8, 16, 32, 64]
MIN_APPEARANCES = 5
MAX_APPEARANCES = MIN_APPEARANCES
N_GUESSES = 200
FEATURES = OrderedDict([
    (LM, None),
    (DEEP, None),
    (ANSWER_PRESENT, None),
    (CLASSIFIER, None),
    (WIKILINKS, None),
    (MENTIONS, None)
])

COMPUTE_OPT_FEATURES = [ANSWER_PRESENT, CLASSIFIER, WIKILINKS, LABEL]
DEEP_OPT_FEATURES = [DEEP]
MEMORY_OPT_FEATURES = [LM, MENTIONS]
LM_OPT_FEATURES = [LM]
MENTIONS_OPT_FEATURES = [MENTIONS]


@lru_cache(maxsize=None)
def get_treebank_tokenizer():
    return TreebankWordTokenizer().tokenize


@lru_cache(maxsize=None)
def get_punctuation_table():
    return dict.fromkeys(
        i for i in range(sys.maxunicode) if unicodedata.category(chr(i)).startswith('P'))
