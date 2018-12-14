import React from 'react';
import ReactDOM from 'react-dom';
import Navigation from './Navigation.jsx';
import DropzoneComponent from 'react-dropzone-component';
import { Link } from 'react-router-dom';
import Options from './Options.jsx';
import Button from '@material-ui/core/Button';
import { withStyle } from '@material-ui/core/styles';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import Icon from '@material-ui/core/Icon';
import DeleteIcon from '@material-ui/icons/Delete';
import QuerybyID from './QuerybyID.jsx';

class Upload_contigs extends React.Component {

    constructor(props) {

        super(props);

        fetch('api/profiling/upload/', {method:'POST'})
        .then(function(res){
           return res.json();
        }).then(function(batch){
           return getID(batch);
        });

        var getID=function(data){
            window.batchid = data.id;
        };


        // TODO: poor performnce issue with everytime load the component will
        // fetch API once.

        window.databaseName = "";
        window.fileName = [];

        this.state = {
            to: "/",
            upload_confirm: false,
            switch: false,
        };

        this.djsConfig = {
            dictDefaultMessage:"Drop files or click to upload contigs",
            addRemoveLinks: true,
            acceptedFiles: ".fasta,.fa,.fna",
            autoProcessQueue: false,
            parallelUploads: 200,
            init:function(){
                this.on("sending", function(file, xhr, formData){
                    formData.append("batch_id", window.batchid);
                });
                this.on("success", function(file){
                    window.fileName.push(file.name);
                });
            }
        }

        this.componentConfig = {
            iconFiletypes: ['.fasta','.fna','.fa'],
            showFiletypeIcon: true,
            postUrl: 'api/profiling/sequence/'
        };

        this.dropzone = null;
    }

    handlePost() {
        
        let fileCheck = this.dropzone.files.length;

        if(fileCheck < 5){
            alert('Please upload at least 5 files');
            return ;
        }

        if(window.databaseName == ""){
            alert('Please choose a database !');
            return ;
        }


        this.dropzone.processQueue();
        this.setState(state => ({ upload_confirm: true , to: '/profile_view' ,
            switch: true }));

    }

    submit(){


        if (this.state.upload_confirm == false){
            alert('Please upload files first! (At least 5 files)');
            return ;
        }

        var scheme = {};
        scheme.occurrence = "95";
        scheme.database = window.databaseName;
        scheme.id = window.batchid;
        fetch('api/profiling/profiling-tree/', {
            method:'POST',
            headers: new Headers({'content-type': 'application/json'}),
            body: JSON.stringify(scheme)
        });

    }

    remove(){
        
        this.dropzone.removeAllFiles();
        
        this.setState(state => ({ to: '/', upload_confirm: false, switch: false }));
        fetch('api/profiling/upload/', {method:'POST'})
        .then(function(res){
           return res.json();
        }).then(function(batch){
           return getID(batch);
        });

        var getID=function(data){
            window.batchid = data.id;
        };
    }

    
    render() {

        const config = this.componentConfig;
        const djsConfig = this.djsConfig;
        const eventHandlers = {
            init: dz => this.dropzone = dz,}

        return (
            <div>
                <Navigation value={0}/>
                <div>
                    <Options switch={this.state.switch} />
                </div>
                <DropzoneComponent config={config} eventHandlers={eventHandlers} 
                    djsConfig={djsConfig} />
                <br />
                <br />
                <div style={{ display:'flex', justifyContent:'center', alignItems:'center'}}>
                    <font> NOTICE: Please use &nbsp;
                        <a href="http://cab.spbu.ru/software/spades/" target="_blank">SPAdes</a>
                        &nbsp; to assembly before upload. 
                    </font>
                </div>
                <br />
                <br />
                <div style={{ display:'flex', justifyContent:'center', alignItems:'center'}}>
                    <Button variant="contained" color="default" onClick={this.handlePost.bind(this)}>
                        Upload
                        &nbsp;&nbsp;
                        <CloudUploadIcon />
                    </Button>
                    &nbsp;&nbsp;&nbsp;&nbsp;
                    <Button variant="contained" color="secondary" onClick={this.remove.bind(this)}>
                        Remove all files
                        &nbsp;&nbsp;
                        <DeleteIcon />
                    </Button>
                </div>
                <br />
                <br />
                <div style={{ display:'flex', justifyContent:'center', alignItems:'center'}}>
                    <Link to={this.state.to} style={{ textDecoration:'none' }}>
                        <Button variant="contained" color="primary" onClick={this.submit.bind(this)}>
                            profiling
                            &nbsp;&nbsp;
                            <Icon>send</Icon>
                        </Button>
                    </Link>
                </div>
                <br />
                <br />
                <div style={{ display:'flex', justifyContent:'center', alignItems:'center'}}>
                    <font size="4"> You can also use batch ID to query your data.</font>
                </div>
                <br />
                <div style={{ display:'flex', justifyContent:'center', alignItems:'center'}}>
                    <QuerybyID />
                </div>
                <br />
                <br />
                <br />
            </div>
            );
    }
}


export default Upload_contigs;