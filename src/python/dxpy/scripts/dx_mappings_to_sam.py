#!/usr/bin/env python

import dxpy
import math
import argparse
import re
import subprocess
import sys
import math

#Usage: sample input: dx_MappingsTableToSamBwa --table_id <gtable_id> --output <filename>
#Example: dx_MappingsTableToSamBwa --table_id gtable-9yZvF200000PYKJyV4k00005 --output mappings.sam

MAX_INT=2147483647

parser = argparse.ArgumentParser(description="Export Mappings gtable to SAM format")
parser.add_argument("mappings_id", help="Mappings table id to read from")
parser.add_argument("--output", dest="file_name", default=None, help="Name of file to write SAM to.  If not given SAM file will be printed to stdout.")
parser.add_argument("--start_row", dest="start_row", type=int, default=0, help="If restricting by the id of the gtable row, which id to start at. Selecting regions will override this option")
parser.add_argument("--end_row", dest="end_row", type=int, default=0, help="If restricting by the id of the gtable row, which id to start at. Selecting regions will override this option")                  
parser.add_argument("--region_index_offset", dest="region_index_offset", type=int, default = 0, help="Adjust regions by this amount. Useful for converting between zero and one indexed lists")
parser.add_argument("--region_file", dest="region_file", default="", help="Regions to extract mappings for, in the format ChrX:A-B")
parser.add_argument("--output_ids", dest="output_ids", action="store_true", default=False, help="Write gtable ids as an optional field to allow for easy reimport")
parser.add_argument("--discard_unmapped", dest="discard_unmapped", action="store_true", default=False, help="If set, do not write unmapped reads to SAM")
parser.add_argument("--read_pair_aware", dest="read_pair_aware", action="store_true", default=False, help="If set, every time a paired read is encoutered, both reads will be included if the mate chr+lo+hi of the mate is above that of the enoutered read. If this is not the case, neither will be written. WARNING: read-pair-aware is not guaranteed to output a sorted SAM file.")
parser.add_argument("--reference", dest="reference", default=None, help="Generating a SAM file requires information about the reference the reads were mapped to.  The Mappings SHOULD have a link to their reference, in the case they do not, or you wish to override that reference, you may optionally supply the ID of a ContigSet object to use instead.")

def main(**kwargs):

    if len(kwargs) == 0:
        opts = parser.parse_args(sys.argv[1:])
    else:
        opts = parser.parse_args(kwargs)

    if opts.mappings_id == None:
        parser.print_help()
        sys.exit(1)
    
    mappingsTable = dxpy.DXGTable(opts.mappings_id)
    writeIds = opts.output_ids
    
    regions = []
    if opts.region_file != "":
        regions = re.findall("-L ([^:]*):(\d+)-(\d+)", open(opts.region_file, 'r').read())
    
    name = mappingsTable.describe()['name']
    
    if opts.reference != None:
        originalContig = opts.reference
    else:
        try:
            originalContig = mappingsTable.get_details()['original_contigset']['$dnanexus_link']
        except:
            raise dxpy.AppError("The original reference genome must be attached to mappings table")
    
    try:
        contigDetails = dxpy.DXRecord(originalContig).get_details()['contigs']
    except:
        raise dxpy.AppError("Unable to access reference with ID "+originalContig)

    contigNames = contigDetails['names']
    contigSizes = contigDetails['sizes']
    
    if opts.file_name != None:
        outputFile = open(opts.file_name, 'w')
    else:
        outputFile = None

    header = ""

    for i in range(len(contigNames)):
        header += "@SQ\tSN:"+str(contigNames[i])+"\tLN:"+str(contigSizes[i])+"\n"

    for i in range(len(mappingsTable.get_details()['read_groups'])):
        header += "@RG\tID:"+str(i) + "\tSM:Sample_"+str(i)+"\n"

    if outputFile != None:
        outputFile.write(header)
    else:
        sys.stdout.write(header)

    col = {}
    names = mappingsTable.get_col_names()
    for i in range(len(names)):
        col[names[i]] = i+1

    column_descs = mappingsTable.describe()['columns']

    sam_cols = []; sam_col_names = []; sam_col_types = {}
    for c in column_descs:
        if c['name'].startswith("sam_field_") or c['name'] == "sam_optional_fields":
            sam_cols.append(c)
            sam_col_names.append(c['name'])
            sam_col_types[c['name']] = c['type']

    defaultCol = {"sequence":"", 
                  "name":"", 
                  "quality": "", 
                  "status": "UNMAPPED", 
                  "chr":"", 
                  "lo":0, 
                  "hi":0, 
                  "negative_strand":False, 
                  "error_probability":0, 
                  "qc_fail":False, 
                  "duplicate":False,
                  "cigar":"", 
                  "mate_id":-1, 
                  "status2":"", 
                  "chr2":"", 
                  "lo2":0, 
                  "hi2":0, 
                  "negative_strand2":False, 
                  "proper_pair":False, 
                  "read_group":0}

    #unmappedFile = open("unmapped.txt", 'w')
        
    if len(regions) == 0:

        if opts.start_row > mappingsTable.describe()['length']:
            raise dxpy.AppError("Starting row is larger than number of rows in table")
        elif opts.end_row < opts.start_row:
            raise dxpy.AppError("Ending row is before Start")

        if opts.end_row > 0:
            generator = mappingsTable.iterate_rows(start=opts.start_row, end=opts.end_row, want_dict=True)
        else:
            generator = mappingsTable.iterate_rows(start=opts.start_row, want_dict=True)

        # write each row unless we're throwing out unmapped 
        for row in generator:
            if row["status"] != "UNMAPPED" or opts.discard_unmapped == False:

                writeRow(row, col, defaultCol, outputFile, writeIds, column_descs, sam_cols, sam_col_names, sam_col_types)

    else:
        for x in regions:
            # generate the query for this region
            query = mappingsTable.genomic_range_query(x[0],int(x[1])+opts.region_index_offset,int(x[2])+opts.region_index_offset,mode='overlap',index='gri')

            # for each row in that range
            for row in mappingsTable.iterate_query_rows(query=query):

                #######
                # if the table is paired then we have to partition the mates correctly
                if opts.read_pair_aware == True and "mate_id" in col:

                    # if we have a single read and we wanna store it (is mapped or are storing unmapped)
                    if row[col["mate_id"]] == -1 and (row[col["status"]] != "UNMAPPED" or opts.discard_unmapped == False):

                        writeRow(row, col, defaultCol, outputFile, writeIds, column_descs, sam_cols, sam_col_names, sam_col_types)

                    #################################################################################

                    #If paired read is the left read, write it and grab the right one
                    if row[col["mate_id"]] == 0:

                        writeRow(row, col, defaultCol, unmappedFile, writeIds, column_descs, sam_cols, sam_col_names, sam_col_types)
                        if row[col["status2"]] != "UNMAPPED":
                            #print row[col["chr2"]]+":"+ str(row[col["lo2"]])+"-"+str(row[col["hi2"]])

                            # pull mate from the table
                            query = mappingsTable.genomic_range_query(chr=row[col["chr2"]], lo=row[col["lo2"]], hi=row[col["hi2"]])
                            for mateRow in mappingsTable.iterate_query_rows(query=query):
                                #print mateRow
                                if mateRow[col["mate_id"]] == 1 and mateRow[col["chr2"]] == row[col["chr"]] and mateRow[col["lo2"]] == row[col["lo"]] and mateRow[col["hi2"]] == row[col["hi"]]:

                                    writeRow(mateRow, col, defaultCol, outputFile, writeIds, column_descs, sam_cols, sam_col_names, sam_col_types)
                                    break
                            #print "Mate not found"
                        else:
                            pass
                            #print "Mate unmapped"
                else:
                    if row[col["status"]] != "UNMAPPED" or opts.discard_unmapped == False:

                        writeRow(row, col, defaultCol, outputFile, writeIds, column_descs, sam_cols, sam_col_names, sam_col_types)

    if outputFile != None:
        outputFile.close()

def tag_value_is_default(value):
    global MAX_INT
    return value == MAX_INT or value == "" or (type(value) == float and math.isnan(value))

def col_name_to_field_name(name):
    if name == 'sam_optional_fields':
        return name
    else:
        return name[10:]

def col_type_to_field_type(col_type):
    if col_type == 'int32':
        return 'i'
    elif col_type == 'float':
        return 'f'
    else:
        return 'Z'

def format_tag_field(name, value, sam_col_types):
    if name == "sam_optional_fields":
        return value
    else:
        return ":".join([col_name_to_field_name(name), col_type_to_field_type(sam_col_types[name]), str(value)])

def writeRow(row, col, defaultCol, outputFile, writeIds, column_descs, sam_cols, sam_col_names, sam_col_types):
    out_row = ""

    values = dict(defaultCol)
    values.update(row)

    flag =  0x1*(values["mate_id"] > -1 and values["mate_id"] <= 1)
    flag += 0x2*(values["proper_pair"] == True) 
    flag += 0x4*(values["status"] == "UNMAPPED")
    flag += 0x8*(values["status2"] == "UNMAPPED") 
    flag += 0x10*(values["negative_strand"] == True) 
    flag += 0x20*(values["negative_strand2"] == True)
    flag += 0x40*(values["mate_id"] == 0) 
    flag += 0x80*(values["mate_id"] == 1) 
    flag += 0x100*(values["status"] == "SECONDARY")
    flag += 0x200*(values["qc_fail"]) 
    flag += 0x400*(values["duplicate"])

    
    chromosome = values["chr"]
    lo = values["lo"]+1
    if values["chr"] == "":
        chromosome = "*"
        lo = 0

    if values["chr2"] == values["chr"]:
        chromosome2 = "="
    else:
        chromosome2 = values["chr2"]

    lo2 = values["lo2"]+1
    if values["chr2"] == "":
        chromosome2 = "*"
        lo2 = 0
        
    readName = values["name"]    
    if readName.strip("@") == "":
        readName = "*"    
    
    if values.get("quality") == None or values.get("quality") == "":
        qual = "*"
    else:
        qual = values["quality"].rstrip('\n')
    seq = values["sequence"]
    
    if values["negative_strand"]:
        seq = reverseComplement(seq)
        qual = qual[::-1]
    
    if values["mate_id"] == -1 or values["chr"] != values["chr2"] or values["chr"] == '' or values["chr"] == '*':
        tlen = 0
    else:
        tlen = (max(int(values["hi2"]),int(values["hi"])) - min(int(values["lo2"]),int(values["lo"])))
        if int(values["lo"]) > int(values["lo2"]):
            tlen *= -1

    out_row = [readName.strip("@"), str(flag), chromosome, str(lo), str(values["error_probability"]), values["cigar"] , chromosome2, str(lo2), str(tlen), seq, qual]
    tag_values = {c: values[c] for c in sam_col_names if not tag_value_is_default(values[c])}

    out_row.extend([format_tag_field(name, value, sam_col_types) for name, value in tag_values.iteritems()])

    ''' Old SAM tags code
    if len(sam_cols) > 0:
        for col_hash in sam_cols:
            write_tag = True
            tag_value = values[col_hash['name']]
            field_name = col_hash['name'][10:]
            if col_hash['type'] == 'int32':
                # if we find the default, do not output tag
                if tag_value == MAX_INT:
                    write_tag = False
                field_type = "i"
            elif col_hash['type'] == 'float':
                if math.isnan(tag_value):
                    write_tag = False
                field_type = "f"
            else:
                if tag_value == "":
                    write_tag = False
                field_type = "Z"

            if write_tag:
                if col_hash['name'] != "sam_optional_fields":
                    out_row = "\t".join([out_row, ":".join([field_name, field_type, str(tag_value)])])
                else:
                    out_row = "\t".join([out_row, row["sam_optional_fields"]])
    '''
   
    out_row.append("RG:Z:"+str(values['read_group']))
    
    if writeIds:
        out_row.append("ZD:Z:"+str(row[0]))
    out_row = "\t".join(out_row) + "\n"

    if outputFile != None:
        outputFile.write(out_row)
    else:
        sys.stdout.write(out_row)


def reverseComplement(seq):
    rc = {"A":"T", "T":"A", "G":"C", "C":"G", "a":"T", "t":"A", "c":"G", "g":"C"}
    result = ''
    for x in seq[::-1]:
        result += rc.get(x, x)
    return result
        

if __name__ == '__main__':
    main()

