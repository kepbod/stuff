#!/usr/bin/env python3

'''
Usage: find_site.py [options] -r REF -g GENOME -b BIGWIG <rs_site>

Options:
    -h --help                      Show help message.
    --version                      Show version.
    -r REF --ref=REF               Gene annotation.
    -g GENOME --genome=GENOME      Genome FASTA file.
    -b BIGWIG --bigwig=BIGWIG      PhastCons BigWig file.
    -p THREAD --thread=THREAD      Threads. [default: 5]
    --intron-length=LENGTH         Minimum intron length. [default: 10000]
    --min-phastcons=PHASTCONS      Minimum PhastCons. [default: 0.9]
    --min-distance=DISTANCE        Minimum distance to splicing sites.
                                   [default: 2000]
    --min-score=SCORE              Minimum splicing site score for 5ss.
                                   [default: 5]
'''

import re
from multiprocessing import Pool
import pyBigWig
from seqlib.ngs import check_fasta
from seqlib.parse import Annotation
from seqlib.seq import dna_to_rna
from maxentpy.maxent import score5, load_matrix5

__author__ = 'Xiao-Ou Zhang <xiaoou.zhang@umassmed.edu>'
__version__ = '0.0.1'


def find_rs(options):
    # parse options
    ref = Annotation(options['--ref'])
    min_intron_length = int(options['--intron-length'])
    # prepare to parse intron regions
    rs_intron_set = set()
    p = Pool(int(options['--thread']))
    results = []
    for isoform in ref:
        chrom, gene, strand = isoform.chrom, isoform.gene, isoform.strand
        for start, end in zip(isoform.intron_starts, isoform.intron_ends):
            intron_length = end - start
            if intron_length < min_intron_length:  # short intron
                continue
            intron_info = '\t'.join([gene, chrom, str(start), str(end), strand,
                                     str(intron_length)])
            if intron_info in rs_intron_set:  # duplicated intron
                continue
            rs_intron_set.add(intron_info)
            results.append(p.apply_async(parse_intron, args=(options, chrom,
                                                             start, end,
                                                             strand,
                                                             intron_info)))
    p.close()
    p.join()
    # output results
    with open(options['<rs_site>'], 'w') as outf:
        for r in results:
            rs_intron, rs_site = r.get()
            if rs_intron:
                outf.write('%s\t%s\n' % (rs_intron, ','.join(rs_site)))


def parse_intron(options, chrom, start, end, strand, intron_info):
    # fetch fasta
    fa = check_fasta(options['--genome'])
    intron_fa = dna_to_rna(fa.fetch(chrom, start, end), strand)
    # load matrix
    matrix5 = load_matrix5()
    # parse options
    phastcons_f = pyBigWig.open(options['--bigwig'])
    min_distance = int(options['--min-distance'])
    min_score = float(options['--min-score'])
    min_phastcons = float(options['--min-phastcons'])
    # start to parse rs sites
    rs_list = []
    for m in re.finditer('AGGT', intron_fa):
        if strand == '+':
            pos = start + m.start() + 2
            left_dist, right_dist, dist_flag = cal_distance(pos, start, end,
                                                            min_distance)
            if not dist_flag:  # not enough distance
                continue
            ss5_seq = dna_to_rna(fa.fetch(chrom, pos - 3, pos + 6))
            if ss5_seq.find('N') != -1:  # ensure there is no N
                continue
            ss5, score_flag = cal_score(ss5_seq, matrix5, min_score)
            if not score_flag:  # not high score
                continue
        else:
            pos = end - m.start() - 2
            left_dist, right_dist, dist_flag = cal_distance(pos, start, end,
                                                            min_distance)
            if not dist_flag:  # not enough distance
                continue
            ss5_seq = dna_to_rna(fa.fetch(chrom, pos - 6, pos + 3),
                                 strand='-')
            if ss5_seq.find('N') != -1:  # ensure there is no N
                continue
            ss5, score_flag = cal_score(ss5_seq, matrix5, min_score)
            if not score_flag:  # not high score
                continue
        phastcons = phastcons_f.stats(chrom, pos - 2, pos + 2)[0]
        if phastcons is None or phastcons < min_phastcons:  # not conserved
            continue
        rs_feature = '%d|%d|%d|%f|%f' % (pos, left_dist, right_dist, ss5,
                                         phastcons)
        rs_list.append(rs_feature)
    if rs_list:
        return (intron_info, rs_list)
    else:
        return (None, None)


def cal_distance(pos, start, end, min_distance):
    left_distance = pos - start
    if left_distance < min_distance:
        return (None, None, False)
    right_distance = end - pos
    if right_distance < min_distance:
        return (None, None, False)
    return (left_distance, right_distance, True)


def cal_score(ss5_seq, matrix5, min_score):
    ss5 = score5(ss5_seq, matrix=matrix5)
    if ss5 < min_score:
        return (ss5, False)
    else:
        return (ss5, True)


if __name__ == '__main__':
    from docopt import docopt
    find_rs(docopt(__doc__, version=__version__))
