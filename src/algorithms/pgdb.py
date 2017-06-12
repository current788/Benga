import json
import os
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
from Bio import SeqIO

from src.models import logs
from src.utils import files, seq, docker, cmds
from src.utils import operations


def parse_filenames(path, ext=".fna"):
    return [name for name in os.listdir(path) if name.endswith(ext)]


def format_contigs(filenames, input_dir, working_dir):
    namemap = {}
    for i, oldname in enumerate(filenames, 1):
        newname = "Genome_{}.fa".format(i)
        namemap[oldname] = newname
        with open(files.joinpath(working_dir, newname), "w") as file:
            for j, contig in enumerate(SeqIO.parse(files.joinpath(input_dir, oldname), "fasta"), 1):
                seqid = "G_{}::C_{}".format(i, j)
                SeqIO.write(seq.replace_id(contig, seqid), file, "fasta")
    return namemap


def move_file(annotate_dir, dest_dir, ext):
    for folder in os.listdir(annotate_dir):
        path = files.joinpath(annotate_dir, folder)
        for file in os.listdir(path):
            current_file = files.joinpath(path, file)
            if file.endswith(ext):
                os.rename(current_file, files.joinpath(dest_dir, file))


def create_noncds(database_dir, gff_dir):
    noncds = defaultdict(list)
    for file in os.listdir(gff_dir):
        name, ext = file.split(".")
        for line in open(files.joinpath(gff_dir, file), "r").read().splitlines():
            if line.startswith("##sequence") or line.startswith("##gff"):
                continue
            if line.startswith("##FASTA"):
                break

            token = line.split("\t")
            seq_type, annotation = token[2], token[8]

            if annotation.startswith("ID="):
                prokkaid = annotation.split(";")[0][3:]
                if seq_type != "CDS":
                    noncds[name].append(prokkaid)
    with open(files.joinpath(database_dir, "nonCDS.json"), "w") as file:
        file.write(json.dumps(noncds))


def extract_profiles(roary_matrix_file, locusmeta_file, paralogmeta_file, metadata_cols=14):
    matrix = pd.read_csv(roary_matrix_file)
    isolates = len(matrix.columns) - metadata_cols

    save_not_appear_once_locus_metadata(matrix, paralogmeta_file)
    matrix = save_appear_once_locus_metadata(matrix, locusmeta_file)
    profiles = matrix.iloc[:, metadata_cols:]
    return profiles, isolates


def save_appear_once_locus_metadata(matrix, meta_file, select_col=None):
    if not select_col:
        select_col = ["Gene", "No. isolates", "No. sequences", "Annotation"]
    appear_once_locus = matrix[matrix["No. isolates"] == matrix["No. sequences"]]
    appear_once_locus[select_col].to_csv(meta_file, sep="\t", index=False)
    return appear_once_locus


def save_not_appear_once_locus_metadata(matrix, meta_file, select_col=None):
    if not select_col:
        select_col = ["Gene", "No. isolates", "No. sequences", "Annotation"]
    not_appear_once_locus = matrix[matrix["No. isolates"] != matrix["No. sequences"]]
    not_appear_once_locus[select_col].to_csv(meta_file, sep="\t", index=False)


def collect_allele_infos(profiles, ffn_dir):
    freq = {row["Gene"]: Counter for i, row in profiles.iterrows()}
    new_profiles = []
    for subject, profile in profiles.iteritems():
        ffn_file = files.joinpath(ffn_dir, "{}.ffn".format(subject))
        seqs = {record.id: record.seq for record in SeqIO.parse(ffn_file, "fasta")}

        new_profile = pd.Series(name=subject)
        for locus, allele in profile.dropna().iteritems():
            freq[locus].update([seqs[allele]])
            s = seqs[allele]
            new_profile.set_value(locus, operations.make_seqid(s))
        new_profiles.append(new_profile)
    new_profiles = pd.concat(new_profiles, axis=1).sort_index().sort_index(axis=1)
    return new_profiles, freq


def save_refseq(freq, refseq_file):
    refseqs = {(locus, counter.most_common(1)[0][0]) for locus, counter in freq.items()}
    records = [seq.new_record(locus, sequence) for locus, sequence in refseqs.items()]
    SeqIO.write(records, refseq_file, "fasta")
    return refseqs


def save_locusfiles(freq, locus_dir):
    for locus, counter in freq.items():
        records = [seq.new_record(operations.make_seqid(allele), allele) for allele in counter.keys()]
        seq.save_records(records, files.joinpath(locus_dir, locus + ".fa"))


def save_allele_freq(freq, allele_freq_file):
    allele_freq = {}
    for locus, counter in freq.items():
        allele_freq[locus] = {operations.make_seqid(allele): count for allele, count in counter.items()}
    with open(allele_freq_file, "w") as file:
        file.write(json.dumps(allele_freq))


def make_schemes(locusmeta_file, scheme_file, refseqs, total_isolates):
    mapping = pd.read_csv(locusmeta_file, sep="\t")
    mapping["occurence"] = list(map(lambda x: round(x/total_isolates * 100, 2), mapping["No. isolates"]))
    mapping["sequence"] = list(map(lambda x: refseqs[x], mapping["locus"]))
    mapping[["locus", "occurence", "sequence"]].to_csv(scheme_file, index=False, sep="\t")


def annotate_configs(input_dir, output_dir, logger=None, threads=8, use_docker=True):
    if not logger:
        logger = logs.console_logger(__name__)

    logger.info("Formating contigs...")
    filenames = parse_filenames(input_dir)

    genome_dir = files.joinpath(output_dir, "Genomes")
    files.create_if_not_exist(genome_dir)
    namemap = format_contigs(filenames, input_dir, genome_dir)
    with open(files.joinpath(output_dir, "namemap.json"), "w") as f:
        f.write(json.dumps(namemap))

    logger.info("Annotating...")
    annotate_dir = files.joinpath(output_dir, "Annotated")
    files.create_if_not_exist(annotate_dir)
    if use_docker:
        docker.prokka(genome_dir, annotate_dir)
    else:
        c = [cmds.form_prokka_cmd(x, genome_dir, annotate_dir) for x in namemap.values()]
        with ProcessPoolExecutor(int(threads / 2)) as executor:
            executor.map(os.system, c)

    logger.info("Moving protein CDS (.ffn) files...")
    ffn_dir = files.joinpath(output_dir, "FFN")
    files.create_if_not_exist(ffn_dir)
    move_file(annotate_dir, ffn_dir, ".ffn")

    logger.info("Moving annotation (.gff) files...")
    gff_dir = files.joinpath(output_dir, "GFF")
    files.create_if_not_exist(gff_dir)
    move_file(annotate_dir, gff_dir, ".gff")

    logger.info("Creating nonCDS.json...")
    create_noncds(output_dir, gff_dir)


def make_database(output_dir, logger=None, threads=2, use_docker=True):
    if not logger:
        logger = logs.console_logger(__name__)

    database_dir = files.joinpath(output_dir, "database")
    files.create_if_not_exist(database_dir)

    logger.info("Calculating the pan genome...")
    min_identity = 95
    if use_docker:
        docker.roary(files.joinpath(output_dir, "GFF"), output_dir, min_identity, threads)
    else:
        c = cmds.form_roary_cmd(files.joinpath(output_dir, "GFF"), output_dir, min_identity, threads)
        os.system(c)

    logger.info("Extract profiles from roary result matrix...")
    matrix_file = files.joinpath(output_dir, "roary", "gene_presence_absence.csv")
    locusmeta_file = files.joinpath(database_dir, "locus_metadata.tsv")
    paralogmeta_file = files.joinpath(database_dir, "paralog_metadata.tsv")
    profiles, total_isolates = extract_profiles(matrix_file, locusmeta_file, paralogmeta_file)

    logger.info("Collecting allele profiles and making allele frequencies and reference sequence...")
    ffn_dir = files.joinpath(output_dir, "FFN")
    profile_file = files.joinpath(database_dir, "allele_profiles.tsv")
    profiles, freq = collect_allele_infos(profiles, ffn_dir)
    profiles.to_csv(profile_file, sep="\t")

    refseq_file = files.joinpath(database_dir, "panRefSeq.fa")
    refseqs = save_refseq(freq, refseq_file)

    locus_dir = files.joinpath(database_dir, "locusfiles")
    files.create_if_not_exist(locus_dir)
    save_locusfiles(freq, locus_dir)

    allele_freq_file = files.joinpath(database_dir, "allele_frequency.json")
    save_allele_freq(freq, allele_freq_file)

    logger.info("Making dynamic schemes...")
    scheme_file = files.joinpath(database_dir, "scheme.tsv")
    make_schemes(locusmeta_file, scheme_file, refseqs, total_isolates)
    logger.info("Done!!")

